# data/ — 运行期数据目录

本目录存放**运行时自动生成**的数据，已被 `.gitignore` 排除（仓库里不含任何真实业务数据）。

| 文件 | 说明 |
|---|---|
| `app.db`             | SQLite 数据库。**首次启动 `run.py` 时自动创建并灌入种子数据**（见 `app/storage/seed.py`）。删除后下次启动会重新生成一个空库。 |
| `app.db-wal` / `-shm`| SQLite WAL 模式的临时文件，自动生成。 |
| `settings.json`      | 运营可配置项（客服电话、APPID、公司名等）持久化文件，由管理后台「设置」页写入。不存在时用代码默认值。 |
| `user_sessions.json` | 小程序用户会话 token，运行期写入。 |

> 上面这些都是一次性 / 本地产物，**不要提交到仓库**。`.gitignore` 已默认忽略。

## 例外：`regions.json` 要入库

| 文件 | 说明 |
|---|---|
| `regions.json` | 省市区三级行政区划码表，`/api/regions` 下发给小程序做地址选择器。**不是运行期产物，是随代码部署的静态资源**，`.gitignore` 里为它开了 `!data/regions.json` 例外。缺这个文件会让 `/api/regions` 返回 500，小程序地址页降级成手输省市区。 |

生成 / 更新：

```bash
cd houdan
python3 scripts/build_regions.py                # 拉最新码表重新生成
python3 scripts/build_regions.py --check-only   # 只校验现有文件
```

数据来自 npm 包 `china-division`（原始数据是国家统计局「统计用区划代码」）。
**行政区划每年都有调整**（撤县设区、合并改名），上游包更新后重跑脚本即可；
生成结果里的 `version` 变了，小程序下次冷启动会自动重新拉取缓存。

脚本内置了校验（省级数量、码格式与父子前缀、占位层是否清理干净、关键样本抽查），
不通过会直接退出、不写文件——上游数据结构变了能第一时间发现。
