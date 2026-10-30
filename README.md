# Rules

各规则集存放在独立分支，按客户端和用途分类。域名规则对符合条件的条目进行关键词合并，以减少条目；关键词可能扩大匹配范围。IP 规则与 Mihomo MRS 不做关键词合并。

| 分支 | 规则集 | 文件格式 |
| --- | --- | --- |
| [sing-geoip](https://github.com/cary17/Rules/tree/sing-geoip) | sing-box IP 规则 | JSON、SRS |
| [sing-geosite](https://github.com/cary17/Rules/tree/sing-geosite) | sing-box 域名规则 | JSON、SRS |
| [mihomo-geoip](https://github.com/cary17/Rules/tree/mihomo-geoip) | Mihomo IP 规则 | LIST、YAML、MRS |
| [mihomo-geosite](https://github.com/cary17/Rules/tree/mihomo-geosite) | Mihomo 域名规则 | LIST/YAML：`classical`；MRS：`domain` |
| [egern](https://github.com/cary17/Rules/tree/egern) | Egern 规则 | YAML |
| [loon](https://github.com/cary17/Rules/tree/loon) | Loon 规则 | LIST |
| [surge](https://github.com/cary17/Rules/tree/surge) | Surge 规则 | LIST |

Mihomo 域名订阅的 `.list` / `.yaml` 使用 `behavior: classical`，分别对应 `format: text` / `format: yaml`；原有 `behavior: domain` 配置需要调整。`.mrs` 保持 `behavior: domain`、`format: mrs`，从优化前的原始域名生成。原始数据只有关键词、没有可转换域名时，不生成对应 MRS。
