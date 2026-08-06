# MechResearch-Agent Plan-and-Execute 修复副本

这是从 `E:\yan\hello-agents-1.0.3\mechresearch-agent` 复制出的安全副本，默认保持原来的 **Planner-Executor / DeepResearch** 后端架构，不把前端主链路切到 LangGraph。LangGraph 文件仅作为可选 sidecar 保留，不影响前后端分离模式。

## 为什么这样处理

- LangGraph 可以做前后端分离，但前端是否能打开与 LangGraph 本身无关，关键是 `Vue/Vite` 前端、`FastAPI` 后端、端口和启动目录是否一致。
- 当前后端默认仍使用 `backend/src/agent.py` 中的 `DeepResearchAgent`，主流程是 `Planner -> Search/RAG -> Summarizer -> Reporter -> Evaluator -> PDF Export`。
- 为避免“在项目根目录运行 npm run dev 找不到脚本”的问题，本副本新增了根目录 `package.json` 和 PowerShell 启动脚本。

## 启动方式

### 1. 后端

```powershell
cd C:\Users\EkkO\Documents\agent-learning\mechresearch-agent-plan-execute-fixed
.\start_backend.ps1
```

后端默认地址：`http://127.0.0.1:8002`

如果要执行真实研究任务，请先复制并配置：

```powershell
Copy-Item .\backend\.env.example .\backend\.env
```

### 2. 前端

```powershell
cd C:\Users\EkkO\Documents\agent-learning\mechresearch-agent-plan-execute-fixed
.\start_frontend.ps1
```

前端默认地址：`http://127.0.0.1:5175`

也可以在项目根目录运行：

```powershell
npm run dev
```

### 3. 基础 smoke test

```powershell
D:\conda_envs\deepre3.11\python.exe smoke_test_project.py
```

## 前端打不开时优先检查

- 是否在根目录误运行了 `npm run dev`：本副本已补根脚本；原项目需要进入 `frontend` 后运行。
- 后端是否启动在 `8002`：前端默认读取 `VITE_API_BASE_URL=http://127.0.0.1:8002`。
- 是否缺少前端依赖：进入 `frontend` 后运行 `npm install`，再运行 `npm run dev`。
- 浏览器是否打开了正确端口：Vite 是 `5175`，不是 FastAPI 的 `8002`。
- 本副本前端脚本显式使用 `vite.config.mjs`，避免在受限环境中加载 `vite.config.ts` 时被 esbuild 路径解析卡住。
