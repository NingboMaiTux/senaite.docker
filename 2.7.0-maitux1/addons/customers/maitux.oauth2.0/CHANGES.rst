Changelog
=========

0.1.0 (unreleased)
------------------

- 首个版本：竹云 IDaaS OAuth 2.0 标准授权码模式统一登录，
  含首次登录建号（待授权）、停用拦截、以及每日 EIAM 用户同步。

- 修复 ``logout`` 覆盖从未生效：CMFPlone 把它注册在 ``INavigationRoot`` 上，
  多适配器查找先比 context 再比 request，``for="*"`` 加浏览层也赢不过。
  于是「退出时同时注销竹云会话」和 state Cookie 清理一直是死代码。

- 修复退出后的落地页是 404：Plone 的视图名叫 ``logged-out``（连字符），
  不是 ``logged_out``。同时按 CMFPlone 的做法支持 ``next`` 参数。
