# 2026-11-18 桌面端登录恢复

发布版本 20261118-pm-login-origin。桌面端发布构建缺失环境值 VITE_API_BASE_URL，浏览器登录时先访问自己设备的 localhost:8000 请求登录状态，随后报无法连接。线上后端、数据库和 Redis 的健康接口正常。

按 VITE_API_BASE_URL=same-origin 重新构建桌面资源，校验整包文件并只切换 web 容器。后端、通知进程、持久服务和手机资源沿用下午版本，待迁移为 0。

公网浏览器使用新入口 /assets/index-DyHL0Sgb.js，核对真实 GET /api/auth/me/ 返回 200。浏览器实际构造的登录 POST 目标为 https://erp.cnhitree.com/api/auth/login/，测试在浏览器内拦截该 POST。

应用源码来源为 c8ef06cc322efde2dbb51385c4caf6d027d547cf。桌面包 SHA-256 为 ec6c70125db468039e96213b2ce913e5e1a70837f4a81284e4a82bc9c84e36ee。
