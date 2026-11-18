# S4-Train-Model

独立的 SAP AI Core GitOps 模型部署仓库。复用镜像
`sunyoucai2/effort-model:1.0.3`，通过输入 Artifact 和 Object Storage Key
下载模型到 `/mnt/models/effort_model.pkl`。

## 连接 AI Core

在 AI Core 注册 Git 仓库后，创建 Application：

| 字段 | 值 |
| --- | --- |
| Application Name | `effort-storage-app` |
| Repository URL | `https://github.tools.sap/I578171/S4-Train-Model.git` |
| Revision | `main` |
| Path | `scenarios/effort-estimation/templates` |

同步后应出现 Scenario `effort-estimation-storage`，Executable 显示名称
`effort-model-storage-server`，实际 ID 为 `effort-model-storage-serving`。
其输入参数为 0，输入 Artifact 为 1（`effortmodel`）。

## 配置模型和部署

1. 在资源组 `assessment-agent-group` 下使用现有 Object Storage Key
   `effort-key`。以下地址假设该 Key 的 Path prefix 是 `ml_models`。
2. 在新 Scenario `effort-estimation-storage` 下注册 Artifact：
   Name 为 `effort-artifact-storage`，Kind 为 `model`，URL 为
   `ai://effort-key/effort_model.pkl`。如果 Path prefix 留空，URL 应为
   `ai://effort-key/ml_models/effort_model.pkl`。
3. 创建 Configuration，选择上述 Scenario 和 Executable，将输入
   `effortmodel` 绑定到新 Artifact。
4. 根据 Configuration 创建 Deployment。
5. 检查 `<deployment-url>/v1/health`，确认 `model_loaded` 为 `true`，
   再调用 `/v1/predict` 验证推理。HTTP 200 本身不足以确认模型加载成功。

模型文件需要提前存储在 S3 中。仓库不包含模型权重或访问凭据。
现有本地服务源码支持 `/mnt/models/effort_model.pkl`；实际部署时还需
通过健康接口确认镜像中的加载逻辑正常工作。若 Docker 镜像需要认证，
请在模板中配置 AI Core 对应的 `imagePullSecrets`。

## 从本地测试部署

需要 Python 3，测试脚本只使用标准库，无需安装额外依赖。
先在 Launchpad 确认新 Deployment 状态为 Running，并复制 Deployment ID。
在本仓库根目录执行（PowerShell）：

```powershell
python scripts/test_deployment.py --deployment-id <新DeploymentID> --env-file "../S4MigrationAssessmentAgent-Train/backend/.env" --resource-group assessment-agent-group
```

`--env-file` 读取现有 AI Core 连接凭据，不会复制凭据到仓库。也可以在
当前进程环境中设置 `AICORE_SERVICE_KEY` 后省略该参数。这里使用的是
AI Core Service Key，不是 S3 Object Storage Key 或 GitHub PAT。

脚本会查询 Deployment URL，确认 `/v1/health` 返回 `model_loaded: true`，
然后对 `examples/projects.json` 中的大小两组项目调用 `/v1/predict`，
打印各工作流预测人天和请求耗时。修改该 JSON 文件即可测试真实项目，
或使用 `--samples <文件路径>` 指定其他样例。

样例包含训练源码中的 36 个特征：18 个数值特征、17 个模块标记
（`is_*`），以及 `tshirt_ord`（S=0、M=1、L=2）。模块标记为 0/1。
这些样例用于验证接口能否推理，没有实际人天标签，不能证明预测准确。
判断准确性需要使用未参与训练的真实项目，并逐工作流对比预测和实际人天，
例如计算平均绝对误差 MAE。大小项目的预测也不保证严格单调增加。

### 模型未加载时

平台下载的文件可能保留存储中的目录结构。实际诊断中发现文件位于
`/mnt/models/ml_models/effort_model.pkl`，而现有镜像的加载器只检查
`/mnt/models/effort_model.pkl` 等候选位置，导致服务 Running 但
`model_loaded: false`。此时存储下载已经成功。

当前模板通过启动命令同时检查上述两个挂载路径，把找到的模型链接到
服务支持的 `/tmp/effort_model.pkl`，再启动 `/app/serve.py`，无需重建镜像。
两个位置都不存在时启动会直接失败，并打印检查过的路径。

推送、同步 Application 后，需要创建新 Configuration 和 Deployment，
让新的启动命令生效；现有 Running 部署不会因为同步模板自动更新。
再次运行本地测试时使用新 Deployment ID。可通过服务 `/v1/debug`
的 `mnt` 字段核对实际文件位置，不能仅依据 Artifact URL 推断挂载后的
文件路径。
