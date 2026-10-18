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

在 Windows 构建时，PDFJS 可能生成以句点结尾的许可证文件名。应保全这些文件的原始名称和内容，以已校验的 tar 归档作为 Docker 构建上下文输入；目录上下文可能改变其内容。发布前直接核对镜像内文件哈希，不只检查本机 `dist`。

部署专用 [Gunicorn 26.2.0](https://pypi.org/project/gunicorn/26.2.0/) 与 [Nginx stable 1.30.6-alpine](https://github.com/docker-library/official-images/blob/master/library/nginx) 已固定；Gunicorn 已核对 PyPI 发布并在 Python 3.13 基础镜像实际安装验证，现有业务 requirements 不变。
