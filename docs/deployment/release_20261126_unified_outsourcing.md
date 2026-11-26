# 统一委外入口和丝印提前开单发布核对

发布批次 `20261126-unified-outsourcing`。本轮范围为委外统一入口、车缝建单简化、丝印可在裁好前开单、获准的 `outsourcing.0024_cut_piece_printing_before_schedule`，以及用户本轮确认的面料颜色选择器行高修复。

## 本批临时资源登记

| 资源 | 用途和清理 |
| --- | --- |
| `E:\workspace\_project\project001_haiqu_ERP_CRM\.tmp\release-20261126-unified-outsourcing` | 独占发布树、候选代码、构建和校验回执。发布结束后核对本批清单，解除构建使用的共享依赖链接，清理本批文件。 |
| 本批 `source` Git 工作树 | 由 Git 建立和移除，登记在上述独占目录下，共用工作区的索引保留。 |
| 本机 `hq-unified-outsourcing-schema-261126` 容器 | 按只读挂载的冻结代码预检和执行单项目标迁移，Compose `run --rm` 结束后复核。 |
| `/opt/haiqu-erp/incoming/20261126-unified-outsourcing` | 用于本批制品传输，上线和 Git 回读后定向核验每个文件再清理。正式 context 和审计留存。 |

上批 `release-20261126-cutpiece-processor` 仅作为只读参考。

## 基线与冻结核对

- 正式容器运行批次 `20261126-cutpiece-processor`。后端和通知进程的镜像 ID 为 `sha256:5c1d3ebb1e75cea8bed0082ab7eae729aeaf4e213fbf4acadc035f8ce2530953`，网页为 `sha256:9ae11eca226b428db6b70af870ae922cd50289ec5655253e42705290729a4d82`；检查时均在运行、重启为 0。回读正式发布清单 SHA-256 为 `002c5a15d24837c41cfb2d83cd71e7a166eff25504c4f384fe127f6643ecea23`。
- Git 基线 `bd0b79727a0864e3be83db13b0b0de123d94e708` 相对运行源码 `d163da7173af882634bf51b3e9d3341bb882790a` 仅增加两份上批文档。使用独立工作树冻结 49 个源码路径，含 19 份后端运行文件。旧的独立裁片丝印列表从前端删除，入口并入统一列表。面料组件只取颜色行高修复。冻结清单 SHA-256 为 `b85108fa57dad5096ff1305050052e1e4f4b810c1e639e5828e73447aeff69f3`。
- 正式基线的 608 个桌面文件逐项核对一致。新桌面使用冻结增量和正式配置构建，`vue-tsc -b` 与 Vite 生产构建通过。临时前端编译目录与依赖接合已清理。
- 本机数据库只读预检确认指定目标的待迁移清单只有 `outsourcing.0024_cut_piece_printing_before_schedule`。因 Windows 挂载读取遇到内存分配错误，改用一次性容器的临时源码包并包含报表所需字体，再次预检通过。
- 正式服务器已按相同目标做数据库只读预检，新约束尚不存在，`schedule_product_id` 目前必填。候选版本的 604 份桌面文件和 58 份手机文件组成网页镜像；服务器独立重算了 25 项页面和共享资源差异，与本机一致。原面料颜色选择器的行高修复见 `PinyinFilterSelect` 样式资源。
- 源码提交对象为 `8fa957d2a871238bec1e3d50afb890b05d80d2ff`。候选后端镜像为 `sha256:41c12653d7edc683d05bf72396a69b2b57414fac32ee22bc79453f34c6b7eae9`，网页为 `sha256:88e40470874c665b35d5c7cc2fe887e004a5fdc4923a550f97b0b4ee480d38ce`，服务器候选发布清单 SHA-256 为 `982a380c10725c677ddabffb74e42e58ff2ad4e6c85209ef04ae208c0414f377`。

## 上线与两端回读

- 本机和正式服务器均只执行 `outsourcing.0024_cut_piece_printing_before_schedule`。随后另开只读事务查询 PostgreSQL，`schedule_product_id` 已可空，`tube_schedule_or_piece_print` 约束已验证生效，目标无待执行迁移。
- 本机和正式分别用真实的两名普通跟单查询，候选与本人跟进任务的最新确认 BOM 逐行核对。每人均有 8 个任务和 30 个产品，其中 24 个尚未排产。抽查未排产产品返回 7 个可选裁片。统一列表及其筛选均返回 200，无丝印权限的另一岗位访问丝印候选返回 403。
- 正式仓库读取现有车缝单与来源均返回 200，原有发出和收回权限可用。两处均无现存裁片丝印单供回读。上述业务验证均为只读，本轮真实写入限于授权的迁移。正式后端、网页和通知进程均已切换，600 余个运行文件经过哈希核对，持久服务身份及资源配置检查通过。
- 公网 HTTPS 健康返回 200，5 个业务入口在未登录时转到登录页，4 个匿名受保护接口均返回 401。23 份通过公网实际下载的资源与发布清单摘要匹配，`assets/PinyinFilterSelect-BKgkE_fX.css` 内的面料颜色规则为 `grid-template-rows: none`、`grid-auto-rows: minmax(0, 1fr)`。浏览器页面错误为 0，临时浏览器工作目录已清除。
- 通过独立 Git 索引提交并回读 `origin/master` 为 `8fa957d2a871238bec1e3d50afb890b05d80d2ff`，与正式运行源码一致。正式服务器仅删除核对过文件名及 SHA 的 3 个上传文件，再复查 `/opt/haiqu-erp/incoming/20261126-unified-outsourcing` 已不存在。正式审计回执保存在 `/opt/haiqu-erp/deployment-logs/20261126-unified-outsourcing`。

## 暂存与清理回执

- 本机预检、迁移和只读检查使用的 `hq-unified-outsourcing-schema-261126` 容器已退出，精确名称查询无容器残留。前端构建输入、依赖接合和公网浏览器临时目录均已清理，原项目依赖文件存在。已按登记路径和文件摘要清理交接补丁 `.tmp/unified-entry-20261126.patch` 及登记文件，并复查两者均不存在。
- 本批 49 个候选源码路径与已发布 Git 树核对后，使用 `git worktree remove` 移除独立工作树。再逐一核对 604 份桌面文件摘要，确认仅余这些产物及 40 份本批脚本和回执，目录中没有链接，使用 `Remove-Item -LiteralPath ... -Recurse` 清理本批独占发布目录。复查 `release-20261126-unified-outsourcing` 已不存在，登记工作树和迁移容器均为 0，项目共用依赖仍可读。上批发布目录保留原状。
- 独立浏览器验收留下的 `.tmp/outsourcing-form-qa-20261126` 与其登记文件属于另一套测试资源。该项自动清理受阻，文件数量与体量见[业务验收记录](../implementation/outsourcing_entry_and_print_before_schedule_20261126.md)。
