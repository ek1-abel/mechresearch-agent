# MechResearch-Agent

## 项目简介：
面向工业项目知识管理场景的任务分解的 Plan-and-Execute式驱动的研究系统，支持PDF等形式的本地知识库上传，围绕离线索引阶段、在线检索阶段、总结每个子任务，最后生成带来源、结构化结论和下一步建议的技术调研报告。

## 🔧技术栈：
·FastAPI
·Vue3
·TypeScript
·Vite
·Python
·Tavily
·SSE

## 启动方式

### 1. 后端

```powershell
cd mechresearch-agent\backend
pip install r-requirements.txt
python main.py(conda run main.py)
```

后端默认地址：`http://127.0.0.1:8002`

如果要执行真实研究任务，请先复制并配置：

```powershell
Copy-Item .\backend\.env.example .\backend\.env
```

### 2. 前端

```powershell
cd mechresearch-agent\frontend

前端默认地址：`http://127.0.0.1:5175`
npm run dev
```


## 前端打不开时优先检查

- 是否在根目录误运行了 `npm run dev`：本副本已补根脚本；原项目需要进入 `frontend` 后运行。
- 后端是否启动在 `8002`：前端默认读取 `VITE_API_BASE_URL=http://127.0.0.1:8002`。
- 是否缺少前端依赖：进入 `frontend` 后运行 `npm install`，再运行 `npm run dev`。
- 浏览器是否打开了正确端口：Vite 是 `5175`，不是 FastAPI 的 `8002`。
- 本副本前端脚本显式使用 `vite.config.mjs`，避免在受限环境中加载 `vite.config.ts` 时被 esbuild 路径解析卡住。
