# NodeSeek 签到与抽奖新帖

每天签到，筛选近期抽奖帖子，从评论库随机选择一条参与。**默认只预览；不会因为配置了 Cookie 就自动发布。**

## 本次配置

- 关键词识别：抽奖、抽獎、盖楼、送鸡、送小鸡、随机抽/送、回帖有奖、Giveaway、Raffle 等，同时查看标题和正文摘要。
- 每个北京时间自然日最多成功评论 **10 条**，多次运行共用额度；不足 10 条就少回复，没有新候选就不回复。
- 新帖：发布不超过 24 小时，且状态历史中没有处理记录；同一帖子不会因为跨天而重复评论。
- 发布前重新读取当前原帖，排除已开奖、已结束、已截止、明确过期的日期，以及需要指定口令/回复格式的帖子。原帖必须能识别为允许普通论坛回帖参与。
- 签到独立执行；评论没有候选或 RSS 读取失败不影响此前的签到尝试。`NS_RANDOM=false` 选择固定奖励，`true` 选择试试手气。
- 提交前保存 `pending`，只有新增的本人精确评论得到确认才记为成功。结果不明时保留记录、停止本轮，不自动重发。

## 发现范围和验收边界

目前通过官方公开 RSS `https://rss.nodeseek.com/` 发现新帖。2026-11-25 实测该源返回最近 **20 条**，正文可能是摘要。它适合近期帖子关键词筛选，**不是站内全文搜索，也不保证覆盖全站所有抽奖帖子**；高峰时、两次扫描之间、或抽奖描述不在摘要中时可能漏帖。每小时运行也不能弥补 RSS 已滑出的内容。后续扩大覆盖需实际验证登录后的站内搜索或新帖分页，不能假设存在未公开 API。

规则偏保守，复杂活动规则、相对日期（如“今晚八点”）、等级/购买资格等不能保证正确理解；有疑问应人工查看。指定口令的活动不会套用通用评论。首次启用前人工检查自己已参加的活动；程序可识别当前页上可见的本人回复，但不会遍历全部历史评论页。永久去重从本程序保存的历史开始。

测试使用合成 RSS、HTML 和本机 HTTP 页面。真实账号登录、当前 NodeSeek 页面选择器、真实签到和真实评论结果需要账号环境验收。遇到 Cloudflare/验证码或页面结构变化会停止，不包含验证码处理或访问限制绕过逻辑。GitHub 托管运行器能否通过站点正常访问检查尚未验证。

## 默认十条评论

1. 感谢楼主的抽奖活动，参与一下，祝大家好运！
2. 来参加抽奖，感谢楼主送出的福利！
3. 参与一下，期待这次能有好运气。
4. 感谢分享福利，我也来试试手气！
5. 报名参与抽奖，祝活动顺利！
6. 来凑个热闹，感谢楼主，祝各位好运！
7. 支持一下抽奖活动，希望好运能轮到我。
8. 谢谢楼主的福利，参与抽奖试试运气！
9. 这次抽奖我也参加，感谢楼主！
10. 参与一波，祝大家都能收获好心情！

随机从库中选择，允许不同帖子用到同一句。通用评论不保证满足每场活动的参与资格或保证中奖。

## 本地使用

建议 Python 3.11、已安装的 Chrome。

```powershell
python -m pip install -r requirements.txt
# 无需 Cookie；只筛选公开 RSS，不打开浏览器，不写状态。
python nodeseek_daily.py
# 完全离线的合成样本预览。
python nodeseek_daily.py --feed-file tests/fixtures/giveaways.xml --at 2026-11-25T08:00:00+00:00
```

实际运行前复制 `.env.example` 为本地 `.env`，填写自己的 `NS_COOKIE` 和 `NS_USER_ID`。`NS_USER_ID` 是个人主页 `/space/12345` 末尾的数字，用于确认登录身份和发布结果。Cookie 只放本地忽略文件或 GitHub Secrets，不提交、不粘贴到公开 Issue/日志。

```powershell
python nodeseek_daily.py --live
```

`--live` 会执行真实签到和评论。样本文件和指定时间禁止与此选项组合。多次本地运行必须共用同一个 `state/state.json`；需要换路径可用 `--state-file`。不要删除状态来“重试”，否则会丢失历史去重。不要将同一账号同时部署到互不共享状态的电脑/仓库。

| 配置 | 位置/默认值 | 作用 |
| --- | --- | --- |
| `NS_COOKIE` | 本地 `.env` / Actions Secret | 实际账号操作必填 |
| `NS_USER_ID` | 本地 `.env` / Actions Variable | 实际账号操作必填，数字 ID |
| `NS_RANDOM` | `false`；Actions 沿用同名 Secret | `true` 随机签到奖励，否则固定奖励 |
| `NS_COMMENT_TEXTS` | 默认上述十条；Actions Variable | 可选，用 `\|` 分隔自己的评论 |
| `HEADLESS` | `true` | 无头浏览器 |
| `CHROME_PATH` | 自动检测 | 可选，Chrome 路径；Actions 安装步骤提供 |
| `NS_STATE_BACKEND` | `local`；Actions 固定 `github` | 状态存储，不识别的值会报错 |
| `NS_STATE_BRANCH` | `automation-state` | GitHub 状态分支 |
| `GITHUB_REPOSITORY` | Actions 自动提供 | `owner/repo`，GitHub 状态存储使用 |
| `GH_TOKEN` / `GITHUB_TOKEN` | Actions 自动提供短期令牌 | 仅状态存储需要 Contents 写权限 |

## GitHub Actions

PR 和 `feat/**` 推送只运行测试与离线预览，不读取论坛 Cookie 执行账号操作。定时任务每小时第 17 分钟触发；GitHub 调度可能延迟，不保证准点。

1. 在仓库 Secrets 配置 `NS_COOKIE`，Variables 配置 `NS_USER_ID`。可选配置 `NS_COMMENT_TEXTS`。
2. 确认 `automation-state` 分支有 `state.json`。本仓库已有空的旧版状态，首次实际执行会迁移；有内容的旧状态不会自动丢弃。其他 Fork 若没有此分支，请手动创建并放入 `state.example.json` 的内容，文件名为 `state.json`。
3. 先在 Actions 手动运行 `mode=preview`。该模式读取共享状态和 RSS，不签到、不发布，也不改状态。
4. 实际账号验收通过后，在默认分支手动选择 `mode=live`。如需定时实际执行，再设置仓库 Variable `NS_LIVE=true`；未设置时定时运行也只预览。非默认分支禁止 live。
5. 若工作流因长期不活跃而停用，需要仓库所有者自行启用。本次开发不会启用它，也不会修改上述 Secrets/Variables。

账号任务使用同一个并发组，运行中不会被新任务取消。状态通过 GitHub Contents API **逐条同步保存**，不是结束后才上传；SHA 冲突或保存失败立即停止。`pending` 未成功持久化之前不会点发布按钮。状态分支不由 PR 测试修改。公开仓库的状态分支会公开帖子 URL、评论文本、账号公开 ID 和结果日期，不保存 Cookie/令牌。

本地和 Actions 如要交替运行同一账号，应统一使用 GitHub 状态存储（配置相同仓库、分支和有权限的令牌）；不要让本地空 JSON 与远程状态各算一份额度。

## 结果不明确时怎么处理

- `confirmed`：已确认成功，永久保留，用于去重和当日计数。
- `pending`：提交前已保存，但进程可能中断；结果待人工检查。
- `unknown`：点击后超时/异常，不能断言没有发出；本轮停止。
- `rejected`：仅用于明确拒绝或人工核实未成功的记录；仍保留同帖去重。

`pending` / `unknown` 在核实前每天都占一个保守额度，避免“超时但实际成功”导致超量，不会自动过期。应先暂停实际运行并到帖子确认，再编辑对应记录：已成功改为 `confirmed`，`quota_dates` 填实际北京时间日期；确定未发出改为 `rejected`，保留原有字段和记录。不要直接删除记录。无法确定就保留 `unknown`。

单次提交跨北京时间零点时，成功记录保守计入两天，可能少发一条，但不会为凑数多发。状态损坏、远程分支缺失、账号绑定不一致时会报错，不会创建一份空额度继续。

## 验证

```powershell
python -m unittest discover -s tests -v
# 可选：真实 Chrome 只操作 127.0.0.1 合成页面，完全不访问论坛账号。
$env:NS_BROWSER_SMOKE='true'
python -m unittest discover -s tests -p test_browser_smoke.py -v
```

浏览器测试验证编辑器填写、原生按钮点击、刷新后结果确认、以及“仅乐观显示但没有服务器保存”不能被记为成功。它验证适配器行为，不代表真实 NodeSeek 页面已经验收。CI 在 Linux 上同样运行该测试。
