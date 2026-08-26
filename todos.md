# 多智能体编排项目开发记录（todos.md）

> 本文档记录架构决策、实施计划与关键教训，防止上下文丢失。遇到任何实现问题先读这里。

---

## 一、当前主线任务：kernel 层工具异步化（异步化迁移）

### 1. 背景与动机

- 目标场景：**多个 orchestration（预计 3+）并发运行**，共享同一事件循环（FastAPI async 端点 + `graph.ainvoke`）。
- 核心诉求：**不阻塞任何东西**——事件循环永不冻结；标准化优先（用户明确：不是越快越好，是做得对、做得好）。
- 讨论结论演进（重要，防止重复踩坑）：
  1. 最初担心"同步工具卡死事件循环" → 提议 kernel 全 async。
  2. 发现 `_fs_mutate` 三工具是**假 async**：`async def` 外壳 + 锁内全是同步 I/O（`open().read()`、`os.replace` 等），唯一真实 await 点是 `asyncio.Lock`。
  3. 用户猜测 langgraph 对同步工具默认丢线程池 → **查源码证实（用户猜对了）**。
  4. 最终定案：**kernel 层 11 个 I/O 工具全 async + 6 个控制工具保持同步纯函数 + bundle 全 async 注册**。

### 2. langchain/langgraph 机制真相（源码证据，勿再质疑）

- 版本：`langchain_core 1.5.3` / `langgraph 1.2.10`（均在 .venv 中）。
- 证据链：
  - `langgraph/prebuilt/tool_node.py` `ToolNode._execute_tool_async`（L1105）：`await tool.ainvoke(call_args, config)`
  - `langchain_core/tools/structured.py` `StructuredTool.ainvoke`（L60-68）：`if not self.coroutine: return await run_in_executor(config, self.invoke, ...)` → **同步工具自动丢线程池**
  - `langchain_core/runnables/config.py` `run_in_executor`（L678-716）：`asyncio.get_running_loop().run_in_executor(None, ...)` → **默认线程池 `min(32, cpu+4)`**  
- **三种工具形态的真实行为**（关键结论）：

  | 形态 | LangGraph 异步执行路径 | 卡事件循环？ |
  |---|---|---|
  | 同步 `def` + `@tool` | 自动 `run_in_executor` → 线程池 | 不卡（但**不可取消**、占线程池） |
  | 真 async（内部真异步 I/O） | `await coroutine` 循环内挂起 | 不卡、**可取消**、不占线程 |
  | 假 async（`async def` + 同步 I/O） | `await coroutine` → 同步段**直接在循环线程跑** | **会卡！最危险** |

- 推论：
  - **假 async 是唯一会卡死事件循环的形态**，绝不允许进入 bundle。
  - async kernel + bundle 同步注册会崩（同步路径返回 coroutine 对象），反之亦然——**注册形态必须与 kernel 形态匹配**。
  - langchain 支持**同步/异步工具混合注册**（`_run_one`/`_arun_one` 双路径），将来单个工具异步化不需要全局改造。

### 3. 最终架构定案（I/O 分层策略）

| kernel 工具 | 形态 | 内部实现 |
|---|---|---|
| `bash` | `async def` | `asyncio.create_subprocess_exec`（真异步、可取消、不占线程）；sandbox-exec 包装照旧 |
| `kill_specific_process` | `async def` | async 子进程（lsof/ps）+ 异步轮询 |
| `view_file` / `glob_tool` / `grep_tool` | `async def` | 内部 `await asyncio.to_thread(核心同步逻辑)` 内聚在 kernel |
| `str_replace` / `write_file` / `clean_dir` | `async def`（保持） | 锁内 I/O 段包 `to_thread`；`asyncio.Lock` 保持（锁的 await 全在事件循环内，I/O 在线程——安全模式） |
| `make_plan` / `edit_plan` / `delete_plan` / `end_orchestration` / `pause_orchestration` / `fanout_subagents` | **同步纯函数** | 无 I/O、微秒级、无阻塞点；分层规范："Kernel 纯函数 + Bundle 异步 Command"，契约在 bundle 层统一为 async |

- bundle 层：全部 `async def` 注册（ToolNode `await`，零适配）。
- **物理边界（诚实认知）**：
  - 事件循环不冻结：100% 可达。
  - 不占线程：仅子进程/网络/LLM 有真异步原语；**Python 生态没有原生异步文件 I/O**（aiofiles 内部也是线程池），文件/CPU 只能 `to_thread`——且 `asyncio.to_thread` 与 langchain `run_in_executor` **共用同一默认线程池**。这是生态极限，也是标准答案。
  - `asyncio.Lock` 等待不占线程（`threading.Lock` 等待会占线程池名额）——这也是保持 asyncio 锁的理由之一。

### 4. 实施顺序（每批全量回归通过后才进下一批）

- **第一批 `_fs_mutate` 三工具**（str_replace/write_file/clean_dir）：
  - 锁内 I/O 段（getsize → read → count/replace → mkstemp → write → chmod → replace → unlink）整体包进同步辅助函数，`await asyncio.to_thread(...)`。
  - 注意：mkstemp→write→chmod→replace 原子序列**必须整体包进一个线程函数**，不可拆分。
  - `asyncio.Lock` 保持；锁的 acquire/release 全在事件循环内。
  - 测试：147 用例**保持 async 基本不动**（pytest-asyncio strict 已是规范）。
- **第二批 `_fs_readonly` 三工具**（view_file/glob_tool/grep_tool）：✅ 已完成
  - async 化 + 内部 `to_thread` 内聚：`_view_file_io`（读取+异常兜底）、`_glob_scan_io`（_glob_walk 调用+统计）、`_grep_io`（收集+搜索+渲染+超时熔断）；校验/路径安全链/正则预编译留事件循环。
  - 对应测试同步 → async 迁移：✅ 已完成（test_fs_readonly_view_file 38 + glob_tool 39 + grep_tool 69 = 146 用例，全部 `@pytest.mark.asyncio` + `await`，跨行调用点逐一补 await）。
  - grep 的 30s 总预算（`GREP_TOTAL_TIMEOUT_SECONDS`）保留内部墙钟轮询，整体包 to_thread，不做双重超时。
- **第三批 `bash` / `kill_specific_process`**（风险最高）：
  - `bash` 工具：✅ 已完成（真异步，非 to_thread）
    - `sandbox/executor.py`：新增 `_exec_async`（`asyncio.create_subprocess_exec` + `start_new_session` + `asyncio.wait_for(proc.communicate(), timeout)`，超时 `killpg(SIGKILL)` 整组终止）+ `arun`（async 版 run，profile 临时文件/截断逻辑照旧）；**同步 `_exec`/`run` 已删除**（import 改 arun 后成死代码链，-123 行）。JAVA_HOME 首次探测（同步 subprocess.run）包 `asyncio.to_thread`。
    - `_bash.py`：`async def bash`，校验/黑名单/路径安全链留事件循环，`import arun as sandbox_run`（模块内名字不变，测试 monkeypatch 兼容）；执行模型写入 docstring。
    - 验证：11 场景手动验证全过（基本执行/退出码/超时 1s 及时返回/**事件循环不阻塞**（2s bash 与 0.5s 任务并发，快任务 0.5s 完成）/killpg 整组终止/黑名单/参数校验/cwd 越界/沙箱违规检测）。
    - 测试同步 → async 迁移：✅ 已完成（test_bash_bash.py 65 用例全绿，2.5s 跑完）
      - 42 个测试全部 `@pytest.mark.asyncio` + `async def`；`read_json(bash(` → `read_json(await bash(`（40 单行 + 2 跨行调用点）；boom 改 `async def`（bash 内部 `await sandbox_run`）；pytest.raises 内裸调用加 await。
      - 并发用例 ThreadPoolExecutor → `asyncio.gather`（真实并发语义不变）；轮询 `time.sleep` → `await asyncio.sleep`；顺手删死 import `signal`（未使用）。
      - 教训：单次 SearchReplace 内多 replace_all 时，后一个 replace_all 可能只替换跨行匹配（工具行为异常），需单独再跑一次 replace_all 修复。
  - `kill_specific_process`：✅ 已完成（真异步）
    - 新增共享探测 `_run_probe`（`create_subprocess_exec` + `wait_for(5s)` + 超时 kill 收尸）；`_lsof_pids`/`_process_comm`/`_pid_alive` 改 async，`_wait_exit` 轮询改 `asyncio.sleep`；主函数校验留循环，`os.kill` 保持同步。`subprocess` import 已删（无残留）。
    - 验证：7 场景手动验证全过（真实 HTTP server SIGTERM 杀/进程退出确认/无进程 error/白名单拦截/参数校验/**SIGKILL 升级**（忽略 SIGTERM 的顽固进程）/轮询期间事件循环不阻塞）。
    - 测试同步 → async 迁移：✅ 已完成（test_bash_kill_specific_process.py 51 用例全绿，1.3s 跑完）
      - 26 个测试全部 `@pytest.mark.asyncio` + `async def`；调用点 `read_json(kill_specific_process(` → `read_json(await kill_specific_process(`（24 处）。
      - **async mock 适配**：`_lsof_pids`/`_process_comm`/`_wait_exit` 已 async，同步 lambda mock 会 TypeError（await 非协程）→ 无状态 mock 改用 `AsyncMock(return_value=...)`/`side_effect`，有状态 fake（计数/分支）手写 `async def`；`os.kill` mock 保持同步（工具内就是同步调用）。
      - TestPidAliveUnit 三用例：mock 对象从 `subprocess.run`（已删）改为 `_run_probe`（AsyncMock 返回 (returncode, stdout) tuple）。
      - 并发用例 `pool.map` → `asyncio.gather`；`ThreadPoolExecutor`/`subprocess` import 已删。
      - **helpers.py 联动**：`_wait_port_free` 同步调用 `_bash._lsof_pids` 未 await → 协程永不等待（RuntimeWarning）+ 端口永远判忙 → 改 `async def` + `await` + `asyncio.sleep` 轮询。教训：**依赖 async 工具的 helper 必须跟着 async 化，不能教条保持同步**。
      - 端到端 3 用例（真进程 SIGTERM/SIGKILL/并发双杀）真实验证通过。
- **第四批 `_web` 工具（新写，直接 async 起步，立范式）**：
  - `httpx.AsyncClient` + `AsyncOpenAI`（真异步）。
  - **需求**：`fetch_web` 抓取内容后，若超过 1 万 chars，用 **secondary model** 对内容做精简（LLM 调用）再返回。
  - 细节待定：抓取实现、阈值常量、精简 prompt、工具内嵌 LLM 调用的确定性与测试策略（后续讨论）。
  - **`web_search` 首轮修复已完成（2026-08-13）**：
    - 校验全部前移到 async 外壳（事件循环）：补 query 非 str / max_results 非 int（bool 排除）/ domains 非 list[str] 类型校验；clamp 留外壳；互斥校验保留。
    - `_web_search_sync` 瘦身为纯网络 I/O（DDG + 域名过滤 + Tavily fallback），docstring 标注"禁止在事件循环线程直接调用"。
    - 死代码清理：删 `import atexit`/`import ipaddress`；16 处尾随空格清零；三个占位 docstring + 文件头约束全部补全。
    - 保留 web_fetch 预留 import（ChatOpenAI/crawl4ai/WEB_SUMMARIZE_TEMPLATE，依赖已装可加载）。
    - 手动验证：8 校验分支全 error JSON、clamp 0→1、真实 DDG 搜索 5 条、白/黑名单过滤生效；全量回归 814 passed。
  - **`web_search` 测试文件已完成（2026-08-13）**：tests/test_web_web_search.py，37 用例全绿（1.0s）。
    - 全程 mock 不触网：DDGS/TavilyClient 同步 fake（_web_search_sync 在线程池同步调用，无需 AsyncMock），settings.tavily_api_key 用 monkeypatch 控制降级分支。
    - 校验类 autouse fixture 断言 last_call is None：校验失败不得发起任何搜索请求（防校验漏洞偷偷触网）。
    - 覆盖：校验 17（类型/长度/互斥/bool 排除）+ clamp 3（text 放大 3 倍参数断言）+ DDG 主路径 2 + 域名过滤 3（含 notgithub.com 负例）+ 降级链 3 + 纯函数 9。无并发用例（用户拍板：provider 能力稍测即可）。
    - **`web_fetch` 测试已完成（2026-08-21）**：tests/test_web_web_fetch.py，44 用例全绿（0.4s）。
    - 全程 mock 不触网：conftest 新增 `fake_crawler`（真异步 arun，返回 (fit, raw) markdown 可配置）
      与 `fake_tavily`（补 extract 方法，与 web_search 共用 TavilyClient fake）；settings.tavily_api_key
      用 monkeypatch 控制回退分支；`_summarize_with_llm` 用 monkeypatch 固定摘要结果。
    - 覆盖：校验 17（url/prompt 类型+长度+协议+SSRF，autouse fixture 断言校验失败不触网）
      + 主路径 3（短内容直返/raw 回退/长内容摘要）+ 回退链 6（无 key 短路/extract 成功/无结果/
      空内容/双失败合并/长内容摘要）+ 摘要纯逻辑 2 + `_is_private_url` 纯函数 9 参数。
    - 至此第四批 web_search + web_fetch 实现与测试全部完成（search 37 + fetch 44 = 81 用例）。
  - **`web_fetch` 回退路径假 async 已修（2026-08-21）**：
    - `_fallback_fetch` 内 `TavilyClient.extract` 为同步阻塞网络调用（无异步 API），
      在 async 壳内直接调用会卡死事件循环——与本文核心教训同一问题（搜索路径当初
      已用 to_thread 修过，fetch 回退路径漏了）→ 整体包 `asyncio.to_thread`，
      与 web_search 同一范式，docstring 补执行模型说明。
    - 实测：extract 0.5s 慢调用与 0.1s 快任务并发，快任务先完成（事件循环不阻塞）；
      无 key/空结果/空内容错误分支不变；全量回归 851 绿。
    - 教训：**新写 async 工具时所有内部同步库调用点都要过一遍 to_thread 检查**（ddgs/tavily
      均无异步 API），不能只修主路径漏回退路径。
- **第五批（收尾）跨工具真实并发测试**：
  - 兑现记忆"并发测试延后"承诺：read-write 竞争、write-write 冲突（同文件锁串行化验证）、跨工具并发（bash + 写文件同时跑）。
  - 全 async 后并发模型锁定"单事件循环"，`asyncio.Lock` 语义确定，可真实交错测试。

### 5. 测试迁移策略（总原则）

- 项目标准：pytest-asyncio 严格模式（async 测试需 `@pytest.mark.asyncio`），helpers.py 辅助函数保持同步（测试里 await kernel 调用即可）。
- 基线：814 用例全绿（迁移前先确认基线）。
- 每批改动范围最小化：写工具测试不动（已是 async）；fs_readonly/bash 测试随工具同步迁移。

### 6. 验收标准

- [ ] 每批全量回归 814+ 用例全绿
- [ ] kernel 11 个 I/O 工具全部 async，无假 async（内部无同步长段）
- [ ] 事件循环不冻结验证（并发场景实测）
- [ ] 并发测试批次完成（read-write / write-write / 跨工具）

---

## 二、其他待办（历史遗留/未来）

- [ ] `bundles/orchestrator.py` 目前为注释模板状态，等 kernel 异步化定稿后恢复并改造（bundle 全 async 注册）。
- [ ] `_web` 工具的 secondary model 精简需求（见第一批四节）——等第四批。
- [ ] docker 相关操作由用户自行执行（docker compose up/down/ps 等），助手只写配置与只读验证（docker compose ps、docker exec 查询）。

---

## 三、项目关键约定（备忘）

- Python 命令必须用项目 venv：`./.venv/bin/python`；测试：`bash scripts/run_tests.sh`（内部通过 dirname 两次调用解析项目根）。
- 代码注释/文档必须中文；禁止魔法数字（统一常量管理）；测试文件 header 三区块 + 多行 docstring。
- 分层规范：Kernel 纯函数（控制工具：无 IO、无锁、无 async）+ Bundle 异步 Command。
- 用户昵称“小鲸鱼”（deepseek v4 flash）；偏好纯粹技术向对话。





========================================================================================================================

# 附录：Example Run 图解（为什么必须异步化——单进程多前端窗口并发）

> 场景：一个后端进程（事件循环 ×1）+ 三个前端窗口（三个 orchestration 并发跑）。
> 这是用户的真实用法（非多进程/非分布式）。
> 关键认知：事件循环是单线程的，同一时刻只能干一件事；谁在事件循环里“同步等待”，全世界都得等他。

## 改造之前（同步工具 / 假 async）——世界陪葬

```
t=0s      A: bash 开始 → subprocess.run(30s) 同步等待  ← 占死循环线程
          B: view_file 排队……（它只需要 1ms！）
          C: grep_tool 排队……（它只需要 100ms！）
t=1s      A: 还在等 npm install
          B: 还在排队，页面转圈
          C: 还在排队
t=10s     A: 还在等。B、C 的用户开始骂人
t=30s     A: 终于完成！B、C 突然“活过来”，一瞬间各自干完

结果：B 读个文件花了 30 秒，C 搜个代码花了 30 秒——他们没做错任何事，
只是运气差，跟 A 撞在同一秒。系统表现 = “全体周期性卡死”。
```

## 改造之后（async + to_thread / 真异步）——各等各的

```
t=0s      A: bash 开始 → 丢进线程池（不占事件循环！）→ 事件循环空闲
          B: view_file 开始 → 丢进线程池 → 1ms 后拿到结果 → B 继续自己的流程 ✓
          C: grep_tool 开始 → 丢进线程池 → 100ms 后拿到结果 → C 继续自己的流程 ✓
t=1ms     B 的用户：读完了？这么快，好的，继续
t=100ms   C 的用户：搜完了，继续
t=30s     A 的用户：npm install 跑完了（等了该等的 30s，不冤枉）

结果：B、C 全程无感；A 等的是自己该等的时间。每个人的等待只花在自己身上，不拖累别人。
```

## 为什么不能写“假 async”（async 壳 + 同步内脏）——必须真 async 或 to_thread

```
❌ 错误模板（假 async）：
async def bash(cmd, timeout=30):
    result = subprocess.run(cmd, timeout=30)   # 同步等待！
    return result
# LangGraph 一看是 async → 直接在事件循环里 await → 30s 占死循环 → 回到“世界陪葬”

✅ 正确模板（str_replace 现在的样子）：
async def bash(cmd, timeout=30):
    return await asyncio.to_thread(_bash_sync, cmd, timeout)   # 等待在线程池
# 事件循环全程空闲，B、C 无感
```

## 一句话总结

这次改的是“模式”，不是“性能”；模式对了，将来接入长耗时工具（bash 30s、LLM 几十秒）时，
多个窗口并发才不会互相陪葬。
