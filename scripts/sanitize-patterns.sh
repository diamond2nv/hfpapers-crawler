#!/bin/sh
# =============================================================================
# sanitize-patterns.sh — 脱敏门禁的唯一定义处 (single source of truth)
#
# 消费者有三个，都读这一份，避免模式漂移:
#   1) scripts/pre-push          → 安装为 .git/hooks/pre-push
#   2) scripts/publish-public.sh → 公开线发布门禁
#   3) tests/test_sanitization.py → 本地测试（同一份模式，同一个判据）
#
# 两组模式语义不同，不要混:
#
#   SENSITIVE_*  敏感值 —— 真人 ORCID / 内网 IP / 机器代号 / 个人邮箱 / token。
#                规则文档与门禁实现自身必然含这些模式串，因此有文件级豁免；
#                每条豁免都必须能在注释里写出理由。
#
#   LAYOUT_*     内网布局与项目代号 —— 本地目录布局、私有同级仓库名、内网 wiki 与
#                镜像主机。这一组**只豁免门禁脚本自身**（自指）：它的价值就在于
#                任何文件都不该出现，一旦开了后门，漏的正是最需要拦的一类。
#
# 2026-09-17 补 LAYOUT 组的由来: 一次公开发布准备中发现，`~/Documents/Gitlab/
# forgejo-self-host/<私有项目名>` 这类引用既绕过了旧模式（`/home/[a-z]+` 匹配不到
# `~/`），也把私有项目名写进了包代码的 docstring 与兜底路径。看不见目标类别的检查
# 比没有检查更糟 —— 与 2026-09-11 ORCID 那次是同一个教训。
# =============================================================================

# ── 第一组：敏感值 ────────────────────────────────────────────────────────────
SENSITIVE_PAT='192\.168\.|(^|[^0-9A-Za-z._=:-])10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}([^0-9]|$)|172\.(1[6-9]|2[0-9]|3[01])\.|/home/[a-z]+|HUAWEI|Speaker|\bWSL\b|0000-000[0-9]-[0-9]{4}-[0-9]{3}[0-9X]|sk-[A-Za-z0-9]{16}|@(126|163|qq|gmail)\.com'

# 允许残留（逐条有理由）:
#   AGENTS.md                    规则文档自身（含模式串与占位符表格）
#   .env.template                占位示例 (<windows-host-lan-ip>)
#   tests/test_config.py         已声明占位符 0000-0000-0000-0000
#   docs/**/DOCKER|DISTRIBUTED   标注 "Replace with A's IP" 的示例
#   DEPLOY.md                    同上
#   hfpclawer/zotero/__init__.py 必须点名平台的功能检测代码
#   scripts/pre-push             门禁脚本自身必然含模式串（自指）
#   scripts/publish-public.sh    同上
#   scripts/sanitize-patterns.sh 本文件（模式定义处）
SENSITIVE_ALLOW='AGENTS\.md|\.env\.template|tests/test_config\.py|docs/(cn/)?(DOCKER|DISTRIBUTED)(\.zh-CN)?\.md|DEPLOY\.md|hfpclawer/zotero/__init__\.py|scripts/pre-push|scripts/publish-public\.sh|scripts/sanitize-patterns\.sh'

# 已批准的占位符（AGENTS.md 表格里声明过）
OK_PLACEHOLDER='0000-0002-1825-0097|0000-0000-0000-0000'

# ── 第二组：内网布局与项目代号（只豁免门禁脚本自身）─────────────────────────
LAYOUT_PAT='forgejo-self-host|~/Documents/Gitlab|Path\.home\(\)[^)]*Gitlab|doku\.php|dokuwiki|codeup\.aliyun|gitlab\.zhejianglab|coc-inverse-agent|gsnv-theory|fusion-tech-intelligence'
LAYOUT_ALLOW='scripts/pre-push|scripts/publish-public\.sh|scripts/sanitize-patterns\.sh'
