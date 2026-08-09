# Rules

将 SagerNet 官方规则集的最终 `.srs` 文件反编译为 sing-box 原生规则集 JSON，并同时发布原始 `.srs` 与同名 `.json`。

## 分支

- `main`：GitHub Actions、同步脚本、测试和文档。
- `sing-geoip`：`SagerNet/sing-geoip` 的 `rule-set` 分支产物。
- `sing-geosite`：`SagerNet/sing-geosite` 的 `rule-set` 分支产物。

产物分支只保存规则文件：

```text
<name>.srs
<name>.json
```

同名 `.srs` 和 `.json` 是一对规则文件。

## 自动同步

GitHub Actions 每天北京时间 01:00 运行，对应 UTC cron：

```text
0 17 * * *
```

同时支持 `workflow_dispatch` 手动运行。每次运行都会重新获取两个上游分支、重新计算 SHA-256、重新反编译和验证，不会因为上游没有变化而跳过。

## 处理规则

- 每个上游文件独立反编译和验证。
- 成功文件同时更新 `.srs` 和 `.json`。
- 本次失败但已经发布过的文件，继续保留旧 `.srs` 和旧 `.json`，不被失败输入覆盖。
- 首次出现但失败的文件不会发布。
- 只有上游固定 commit 中已经不存在的文件，才会从产物分支删除。
- 部分文件失败时，成功文件仍然提交，Actions job 最终标记为失败并列出详细原因。
- 全部文件失败时，旧规则文件保持不变，但仍提交一次带运行记录的空提交。

## 可追溯性

每次产物分支提交正文和 GitHub Actions Job Summary 记录：

- 上游仓库、分支和完整 commit SHA
- sing-box 版本
- sing-box 压缩包和二进制 SHA-256
- 本次运行时间和 Workflow run URL
- 上游文件数、成功数、失败数和沿用旧版本数

每次运行都会计算输入 SRS、输出 JSON 和保留旧文件的 SHA-256。SHA-256、上游 commit、sing-box 版本、成功/失败数量以及详细失败原因只写入提交正文和 GitHub Actions Job Summary，不写入产物分支文件，因此产物分支始终只有 `.srs` 和 `.json`。

## 来源

- [SagerNet/sing-geoip](https://github.com/SagerNet/sing-geoip/tree/rule-set)
- [SagerNet/sing-geosite](https://github.com/SagerNet/sing-geosite/tree/rule-set)
- [sing-box rule-set decompile](https://sing-box.sagernet.org/installation/usage/)

本项目只转换并重新发布规则文件，不声称拥有上游规则数据的版权。上游数据和本项目代码分别遵循各自许可证。

## 本地验证

需要已安装 sing-box：

```bash
bash -n scripts/sync-rules.sh
bash -n .github/workflows/sync-one.sh
bash -n tests/test-sync-rules.sh
python3 -m py_compile scripts/validate-rule-json.py
tests/test-sync-rules.sh
```

GitHub Actions 每次运行都会从 sing-box 官方 GitHub Release 的 `latest` 接口下载当前最新正式版 CLI，校验 Release 提供的 SHA-256 digest（若提供）并记录本地压缩包和二进制 SHA-256，然后处理两个上游分支。不会自行构建 sing-box，也不会长期固定旧版本；这样可以跟随 sing-box 原生规则集格式的同步更新。

## 使用产物

例如，稳定分支的 raw 文件可按以下形式引用：

```text
https://raw.githubusercontent.com/<owner>/Rules/sing-geosite/geosite-google.srs
https://raw.githubusercontent.com/<owner>/Rules/sing-geosite/geosite-google.json
```

JSON 是 SRS 的反编译结果，不是 V2Fly `dlc.dat` 或 MaxMind 原始数据的恢复版本。

## 许可

规则文件的来源、版权和许可归属各自上游项目；本项目代码许可证将在远端仓库发布前单独确认。
