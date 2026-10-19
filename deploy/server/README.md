# ERP 服务器部署

域名为 `erp.cnhitree.com`，使用现有账号及现有数据副本；本地继续开发。服务器数据库和附件位于 `/srv/haiqu-erp`，与本地后续修改互不自动同步。不得混用旧 CRM 的目录、数据库或服务。

白名单构建目录包含 `backend/`、以 `VITE_API_BASE_URL=same-origin` 新构建的 `frontend_dist/`、本目录复制成的 `deployment/`。服务器环境文件为 `/etc/haiqu-erp/server.env`，权限 `600`；保留原有业务开关及邮件加密密钥，使用独立 Django 密钥和数据库密码。

首次创建空目录后，由迁移步骤导入现有数据与附件；不创建额外账号。`media` 需归 UID/GID `10001:10001` 所有，`staticfiles` 需归该用户且允许 Nginx 读取。

镜像当前在本地按白名单 context 构建，再通过 `docker load` 载入服务器；服务器使用 `up -d --no-build`，未来需要在服务器构建时再检查 Buildx。

```sh
install -d -o 70 -g 70 -m 0700 /srv/haiqu-erp/postgres
install -d -m 0750 /srv/haiqu-erp/redis /srv/haiqu-erp/clamav
install -d -o 10001 -g 10001 -m 0750 /srv/haiqu-erp/media
install -d -o 10001 -g 10001 -m 0755 /srv/haiqu-erp/staticfiles
cd /opt/haiqu-erp/releases/<版本号>/context
export ERP_ENV_FILE=/etc/haiqu-erp/server.env ERP_BUILD_CONTEXT="$PWD" RELEASE_TAG=<版本号>
docker compose --env-file "$ERP_ENV_FILE" -f deployment/compose.yml config --quiet
docker compose --env-file "$ERP_ENV_FILE" -f deployment/compose.yml up -d --no-build postgres redis clamav
# 完成数据导入后，明确执行一次迁移；应用启动不会自动 migrate。
docker compose --env-file "$ERP_ENV_FILE" -f deployment/compose.yml run --rm backend python manage.py migrate --noinput
docker compose --env-file "$ERP_ENV_FILE" -f deployment/compose.yml up -d --no-build
docker compose --env-file "$ERP_ENV_FILE" -f deployment/compose.yml ps
```

外层 HTTPS Nginx 仅代理到 `127.0.0.1:18080`，必须覆盖 `Host` 并传入 `X-Forwarded-Proto https`。内层保留该协议头，附件继续走业务 API，禁止公开整个 media。

更新时先保留数据库/附件备份及旧镜像，再完成本地构建和镜像加载、切换新版本 context 目录，执行 `config`、必要迁移和 `up -d --no-build`；不要把本地数据库再次覆盖到已使用的服务器库，也不要执行 `down -v`。

当前工厂试用阶段按用户明确要求不新增服务器备份；这不授权删除已有备份、覆盖数据或自动执行迁移。2026-10-18 更新仅切换应用镜像，不运行迁移或目录导入。增量切换必须显式传入 `RELEASE_TAG`、`ERP_BUILD_CONTEXT`、`ERP_ENV_FILE`，使用 `up -d --no-deps --no-build --pull never backend web`，并核对实际运行镜像 ID、公开网页同源 API 请求及既有数据保全结果。

在 Windows 构建时，PDFJS 可能生成以句点结尾的许可证文件名。应保全这些文件的原始名称和内容，以已校验的 tar 归档作为 Docker 构建上下文输入；目录上下文可能改变其内容。本机 Docker 对首条记录为 PAX 扩展头的归档会误判为 Dockerfile，构建归档使用 GNU tar 格式并通过二进制管道输入；文件名和内容不变。发布前直接核对镜像内文件哈希，不只检查本机 `dist`。

部署专用 [Gunicorn 26.2.0](https://pypi.org/project/gunicorn/26.2.0/) 与 [Nginx stable 1.30.6-alpine](https://github.com/docker-library/official-images/blob/master/library/nginx) 已固定；Gunicorn 已核对 PyPI 发布并在 Python 3.13 基础镜像实际安装验证，现有业务 requirements 不变。

## OCI 镜像增量传输

`image_delta.py` 使用 Python 3.11+ 标准库处理未压缩的 `docker image save` OCI tar。两端先导出各自已有的应用镜像；只上传新归档的入口元数据及服务器基线缺失的 blob，不改变镜像配置、层或构建证明。不支持旧式 Docker tar、未知归档路径、软硬链接或摘要不符的文件，遇到这些情况停止，不转换格式。

```sh
# 服务器：基线镜像必须是已核对 ID 的旧版本，且保持旧镜像用于回退。
docker image save -o existing-images.tar <旧后端标签> <旧网页标签>
python3 image_delta.py inventory existing-images.tar --output existing-images.index.json
# 本机：下载上述索引；新全包、增量包和 recipe 都采用本次发布独占路径。
docker image save -o new-images.tar <新后端标签> <新网页标签>
python image_delta.py delta new-images.tar --baseline existing-images.index.json --output images-delta.tar --recipe images-recipe.json
# 仅上传工具、images-delta.tar 和 images-recipe.json；随后在服务器执行：
python3 image_delta.py reassemble existing-images.tar --delta images-delta.tar --recipe images-recipe.json --output new-images.tar
python3 image_delta.py verify new-images.tar --recipe images-recipe.json
docker image load --input new-images.tar
```

工具输出源全包大小、增量大小、复用 blob 数量及字节数；recipe 记录每个源成员的大小、SHA256、包含在增量包内的成员和增量包摘要。重组流式读取基线与增量，不解包层、不修改 Docker 数据目录；校验失败返回非零退出码，并删除本次已创建的部分输出，始终拒绝覆盖既有文件。外层 tar 的头部或填充可以不同，全部文件成员内容必须与 recipe 一致。

加载后另外核对两张新镜像的完整 ID，再按上文显式版本号切换；归档校验不能代替运行版本和真实页面验收。源全包及 recipe 保留到加载与版本核验结束；随后按任务资源登记清理本次临时归档，保留脱敏验收证据和旧版本镜像，不做全局 prune。此流程不引入常驻 blob 缓存或 BuildKit 缓存。

工具测试：`python -B deploy/server/test_image_delta.py`。测试仅创建项目 `qa/.image_delta_unit_temp` 下的独占小型归档，结束自动清理，不调用 Docker 或真实数据库。
