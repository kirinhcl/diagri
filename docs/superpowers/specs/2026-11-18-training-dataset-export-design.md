# 训练数据集导出（变量目录第二阶段）：设计

**接续：** `2026-11-17-variable-catalog-design.md`（第一阶段，已合并为 PR #17）。本文取代那份文档的第 11 节。

## 1. 意图

DiAGRI 的实验数据会用来训练一个作物基础模型（crop foundation model）。训练时，DiAGRI 的数据会和其他来源的数据（公开数据集、别的实验室或温室）混在一起。合并由用户团队自己做：他们自己写训练流程，没有外部规定的接收格式。

所以这一阶段要交出的，不是一份登记实验用的公开记录，而是能直接拿去训练、能和别人的数据按行合并的数据集。具体要做到五点：

1. **含义一致。** 同一个变量在所有实验里意思相同。第一阶段的目录已经保证了 DiAGRI 内部的一致；和外部数据对齐要靠本体术语。
2. **不泄漏。** 留出批次的结果永远不进导出。它们是这个基础模型将来做正式评估的测试集。
3. **可复现。** 同样的输入，导出结果逐字节相同；每份导出都能追溯到一个快照的摘要。
4. **不靠猜。** 本体映射错了比没有更糟：合并时会把两个不同的量悄悄当成一个。没有核对过的术语就留空，并明确标出来。
5. **通用工具能读。** 不用写 DiAGRI 专用的解析代码。

**现状（`main`，de2cd64）：**

- `archive/export.py` 的 `export_miappe` 写一份项目自定的嵌套 JSON（`miappe.json`）。没有任何命令行、接口、控制台按钮或 agent 工具调用它，wiki 写明它只是测试覆盖的库函数。
- 快照只由研究员 agent 在阶段结束时冻结，冻结时已套用留出过滤。快照内容：`samples`、`samples_untrusted`、`actions`、`measurements`、`interventions`、`frozen_periods`、（有运行单时）`manual_tasks` 和 `task_records`，加上第一阶段的 `catalog.json`。
- 没有图像：`photo` 只是一种人工任务，照片不进存档。
- 没有品种字段，作物只是协议里的自由文本 `crop`。
- 目录的单位是 UCUM 代码（`Cel`、`[ppm]`、`%`），`refs` 字段已存在但全部为空。

## 2. 目标、非目标、反目标

**目标**

1. 一条命令行命令把一个快照导出成一个训练数据集目录：几张扁平 CSV 表、一张变量表、一份 `croissant.json`。
2. 目录条目带人工核对过的本体术语；单位带 UO 术语。
3. 协议带作物物种（`crop_taxon`，必填）和品种（`cultivar`，可选）。
4. 导出不包含任何按**当前**留出登记应被留出的结果，即使登记晚于快照冻结。
5. 同一快照、同一目录、同一留出登记、同样的命令参数，导出逐字节相同。
6. MLCommons 的 `mlcroissant` 能加载导出并逐行读出每张表。

**非目标**

- 图像。如果模型需要，那是一个独立项目。
- MIAPPE ISA-Tab、BrAPI、公开存档、DOI。将来需要时可以从同一份元数据另写导出。
- 单位换算。数值保持目录单位，换算由合并方统一做。
- Parquet。不为它引入 pyarrow 依赖。
- 控制台按钮、HTTP 接口、MCP 工具、agent 触发。
- 把多个快照合成一个数据集。每个快照一个目录，合并在训练流程里做。
- 导出 `manual_tasks` 和 `task_records`。没有图像时它们对训练没有用。
- 把设备自身状态（调光、风扇档位、插座开关）收进目录或配本体术语。见第 8 节。

**反目标（即使代码能跑，出现这些也算失败）**

- 导出里出现留出批次的结果。
- 导出里出现没有人核对过的本体术语。
- 导出修改了存档、快照或数据库里的任何东西。
- 某些行被悄悄丢掉，元数据里却没有交代。
- 操作员的真实身份或备注原文进入导出。
- 两次导出同一输入得到不同的文件。

## 3. 约束（来自现有代码和外部规范）

- **快照。** `archive/snapshot.py` 把每类记录写成 `<name>.jsonl`，清单里存每个文件的 sha256。现有导出读文件前先校验快照，新导出照做。
- **传感器记录** `SampleRecord`：
  - `captured_at` 可能为 `None`（设备没给采集时间），`received_at` 总有值，`clock_synced` 表示设备时钟是否已同步，`quality` 是质量标记。
  - 读数在 `data["sensor"]` 下，键是设备键（`temp`、`humi` 等，即目录别名）。
  - `data` 下还有设备上报的自身状态：`light.level`、`light.on`、`fan.level`、`blower.level`、`outlet.O1.on` 等（数值，`on` 为 0 或 1；`snapshot._numbers` 把嵌套键用点连起来）。这些是控制器的实际状态，和 `actions` 里"发出的指令"不是一回事。
  - 可信与不可信的记录分在两个文件里。
- **传感器卡值时段** `FrozenPeriod`：某个传感器从 `first_at` 起一直报同一个值，尚未恢复。这段时间的读数不可靠。
- **人工测量** `ManualMeasurement`：原始记录永不修改，更正是一条新记录，用 `corrects` 指向被更正的那条。快照包含更正前后的记录。第一阶段起录入时强制使用目录单位。
- **实验单元。** `Allocation(round, block, unit, treatment_id)`。测量值归到哪个单元，按报告里的规则：轮次取自实验；一轮只有一个单元时，整个实验就是这个单元；否则用测量的 `position` 对应 `unit`（见 `agents/handlers_report.py` 的 `_missing_fraction`）。导出必须复用同一条规则，不能另写一套。
- **留出登记** `research/holdout.py`：
  - `holdouts(project_id)` 给出每个留出的 `batch_ids` 和 `outcome_fields`；
  - `development_filter(project_id)` 是数据路径上的判定函数，每次调用都重新读登记；
  - 无法解析的名字按结果对待；某个留出的结果字段有一个无法解析，它的留出批次就全部隐藏；
  - 快照冻结时已经套用了这个过滤，被排除的行不在快照里，清单只记一个数：`measurements_excluded`。
- **目录。** `Variable.refs` 不是定义字段，改它不违反只追加规则，但要让 `version` 加 1。
- **操作员。** `ManualMeasurement.operator`、`ActionRecord.operator` 和干预记录的 `operator` 都是人的身份，属于个人数据。
- **人写的自由文本。**
  - 动作的 `trigger` 会带上操作员的备注：手动操作写成 `manual: <备注>`（`workbench/api.py`），计划灌溉写成 `planned irrigation <task_id>: <备注>`（`workbench/manual_tasks.py`），备注最长 200 字符。
  - 干预记录的 `detail` 只由系统写（看门狗 `executor/watchdog.py`、`runtime_mirror.py`），没有人手输入。
  - 测量的 `batch`、`plant_id`、`position`、`layout_version`，以及协议的研究问题和假设，都由人填写。
- **依赖。** 运行时依赖只有 fastapi、httpx、mcp、pydantic、uvicorn（Linux 上加 bleak）。导出只用标准库。
- **Croissant 1.1**（MLCommons，规范日期 2026-01-29）：
  - `conformsTo` 为 `http://mlcommons.org/croissant/1.1`；
  - 数据集必填项：`name`、`description`、`license`、`url`、`creator`、`datePublished`、`distribution`；
  - CSV 用 `FileObject`（`encodingFormat: text/csv`，可带 `sha256`）声明，`Field` 的 `source.extract.column` 指向列；
  - `Field` 有 `dataType` 和 `references`（外键），`dataType` 可以是外部词表的 IRI；
  - 数据里的 CURIE 前缀在 `@context` 里声明；
  - 支持 PROV-O 的 `prov:wasDerivedFrom` 和 `prov:wasGeneratedBy`；
  - **规范没有单位的概念**，所以单位必须作为数据写进变量表。

## 4. 方案

讨论时比较了三种做法，用户选了 B。

- **A. 在现有 `miappe.json` 上扩展。** 加 `refs`、`crop_taxon`、品种和设施信息，再加一条命令。改动最小。但它是嵌套 JSON，传感器数据在另外的 JSONL 里，训练流程得自己展开和拼接，机器学习工具也读不了这个格式。
- **B. 换成训练用的数据集导出（选定）。** 扁平的长表 CSV，加一张带单位和本体术语的变量表，加一份 Croissant 元数据。`miappe.json` 退役，其中的研究和实验信息并进 `croissant.json`。
- **C. B 加上保留 `miappe.json`。** 将来公开存档时能直接用，代价是两种格式同步维护，而目前没有人用 `miappe.json`。

**选 B 的理由：**

- `miappe.json` 没有调用方，换掉没有代价。
- 训练和合并需要的是扁平、逐列有类型、每个变量带术语的表。
- 用长表（每行是一个时间点上一个变量的一个值）时，各个来源的变量不必相同，合并就是按行拼接，本体术语也只需要在变量表里写一次。

## 5. 目录：本体术语

### 5.1 格式

- `refs` 里每一项是一个 CURIE（`前缀:本地 ID`）。加载时检查格式，前缀必须在下面的白名单里，否则抛 `CatalogError`。白名单同时给出前缀展开成的 IRI 基址，导出时写进 `@context`。
  - `CO_<数字>`（Crop Ontology 的各作物本体）
  - `PECO`
  - `ENVO`
  - `AGRO`
  - `PATO`
  - `UO`
  - `NCBITaxon`
- 新增 `[unit_refs]` 表：键是目录里用到的 UCUM 代码，值是对应的 UO CURIE，例如 `"Cel" = "UO:…"`。加载时检查：每个键都必须是某个条目实际用到的单位，值必须是 `UO:` 前缀。没有核对过的单位就不写。
- 单位用 UCUM 代码表示（机器可读），UO 术语另加 IRI；两者在变量表里各占一列。

### 5.2 填写流程

1. 实现者在 OLS 或 AgroPortal 上逐条查询，为每个条目整理一份候选清单：CURIE、术语标签、本体名称、本体版本或查询日期。
   - 手工性状用 Crop Ontology 的 variable / trait / method / scale；
   - 处理因子用 PECO；
   - 环境量用 ENVO 或 AGRO。
2. **用户逐条确认后才写进 `catalog.toml`。** 只有研究者能判断一个术语的定义是否和这个变量的测法一致。
3. 不确定的条目留空。
4. 写入时 `version` 从 1 变为 2。`catalog.lock.json` 的条目摘要不变（`refs` 不是定义字段），`versions` 里加上 v2 的摘要。

首批只有现有的 8 个条目（6 个传感器、`canopy_area_growth`、`light`）。第一个真实实验的手工变量加进目录时，按同一流程填术语。

## 6. 协议：作物物种和品种

- `ResearchProtocol` 新增 `crop_taxon: str = ""`（NCBITaxon 的 CURIE）和 `cultivar: str = ""`。
- 第一阶段的序列化器推广成"这几个字段为空时不写入"：`variables`、`crop_taxon`、`cultivar`。已保存协议的摘要保持不变，钉住的摘要测试 `43a1b329…` 必须继续通过。
- **保存检查。** 新的协议版本：
  - `crop_taxon` 必须匹配 `^NCBITaxon:[0-9]+$`；
  - `cultivar` 最多 200 个字符。
  - 不合格就拒绝，`reason="protocol_crop_taxon_invalid"`，`params` 为 `protocol_id` 和 `version`。按现有做法在 `denial_codes.py` 登记，并补上控制台的中英文提示。
- **控制台。** 协议表单加两个字段。物种字段的提示写明格式和去哪里查（NCBI Taxonomy），不给具体物种的示例 ID。
- **旧协议。** 目前没有真实数据。开发和模拟用的协议没有 `crop_taxon`，导出时会被拒绝；新一轮用新版本协议即可。

## 7. 导出命令

```
growbridge export-dataset --snapshot <ID> --out <目录> --licence <许可证> --creator <名称> [--url <URL>]
```

- 从配置里的数据目录打开存档、协议存储和留出登记，全程只读。不拿守护进程锁，守护进程运行时也能导出。
- 先写到 `<目录>` 旁边的临时目录，全部写完再改名为 `<目录>`。`<目录>` 已存在就拒绝。
- **拒绝的情况。** 每种情况都给出一条说清原因的消息，以非零状态退出：
  - 快照校验失败；
  - 快照没有 `catalog.json`；
  - 协议没有 `crop_taxon`；
  - `--licence` 或 `--creator` 为空；
  - 有人工测量的单位和目录单位不一致（第一阶段之后不应发生，发生了就说明数据有问题，不能悄悄导出）。
- 导出所用的协议版本，按报告找实验所属协议版本的同一方式确定。
- **输出。** 写出的文件列表、每个文件的行数，以及下面几类计数（同样写进 `croissant.json`）：
  - 未映射的变量；未解析的设备键；
  - 冻结时排除的结果行（清单里的 `measurements_excluded`）和导出时又排除的结果行；
  - 被更正取代的记录；冻结之后又被更正的记录；
  - 去掉的操作员备注；归为 `other` 的触发来源；
  - 没有导出的非数值设备状态。

## 8. 输出的表

所有 CSV：

- UTF-8 编码，LF 换行，第一行是表头。
- 时间统一写成 UTC 的 ISO 8601 格式，精确到毫秒，以 `Z` 结尾。
- 浮点数用 Python 的 `repr`。
- 空值写成空字段。
- 行按下面每张表注明的键排序。

| 文件 | 内容 | 排序键 |
|---|---|---|
| `variables.csv` | `variable_id`, `kind`, `label_en`, `quantity`, `unit_ucum`, `unit_uo`, `method`, `min`, `max`, `refs`（空格分隔的 CURIE）, `mapped`（`refs` 非空时为 true） | `variable_id` |
| `treatments.csv` | `treatment_id`, `name`, `is_control`, `variable_id`（因子）, `value` | `treatment_id`, `variable_id` |
| `units.csv` | `round`, `block`, `unit`, `treatment_id` | `round`, `unit` |
| `sensor_readings.csv` | `time`, `time_source`（`captured` 或 `received`）, `clock_synced`, `sample_id`, `device_id`, `experiment_id`, `stage_id`, `round`, `variable_id`, `raw_key`, `value`, `quality`, `stuck` | `time`, `sample_id`, `raw_key` |
| `sensor_readings_untrusted.csv` | 同上 | 同上 |
| `device_states.csv` | `time`, `time_source`, `clock_synced`, `sample_id`, `device_id`, `experiment_id`, `stage_id`, `round`, `key`（如 `light.level`）, `value`, `quality` | `time`, `sample_id`, `key` |
| `device_states_untrusted.csv` | 同上 | 同上 |
| `measurements.csv` | `time`, `record_id`, `corrects`, `experiment_id`, `round`, `batch`, `unit`, `treatment_id`, `plant_id`, `position`, `layout_version`, `variable_id`, `value`, `method`, `operator` | `time`, `record_id` |
| `actions.csv` | `request_id`, `channel`, `state`, `trigger`（去掉备注后的触发来源）, `planned_level`, `confirmed_level`, `created_at`, `sent_at`, `confirmed_at`, `ran_seconds`, `error_code`, `ended_early_code`, `supersedes`, `operator` | `created_at`, `request_id` |
| `interventions.csv` | `id`, `time`, `stage_id`, `kind`, `detail`（规范化 JSON 字符串）, `operator` | `time`, `id` |
| `withheld.csv` | `holdout_id`, `batch`, `variable_id` | 全部列 |

各列的规则：

- **`time` 和 `time_source`。** 有 `captured_at` 且 `clock_synced` 为真时，`time` 用采集时间，`time_source=captured`；否则用 `received_at`，`time_source=received`。两种时间都不丢，训练方可以按 `time_source` 筛选。
- **`variable_id` 和 `raw_key`。** 设备键按目录解析为 ID。解析不了的键照样导出：`variable_id` 留空，`raw_key` 保留原名，计入"未解析"计数。不丢行。
- **`stuck`。** 读数落在同一传感器的卡值时段内为 true。
- **设备状态。**
  - `device_states.csv` 收 `data` 下除 `sensor` 以外的全部数值叶子，键的拼法与 `snapshot._numbers` 相同；可信与不可信样本分两个文件，和传感器一样。
  - 这些是这台控制器自己的状态（调光百分比、风扇档位、插座开关），不是能跨来源对齐的物理量，本阶段不进目录，也不配本体术语。跨来源可比的光照量是 PPFD 传感器；光周期可以由 `light.on` 推出。
  - 各个键的含义写进 `croissant.json` 的字段描述和 wiki。
  - 非数值叶子不导出，只计数。
- **`measurements.csv` 只放有效值。** 一条记录如果被快照里的另一条记录更正，就不放进这张表，只计数。留下的记录用 `corrects` 指回它更正的那条。
- **冻结后才出现的更正。** 存档里如果有冻结之后才录入的、更正快照内某条记录的新记录，导出不改数值（导出只取决于快照），只在元数据里列出被更正记录的 ID 和数量，提醒训练方。
- **`unit` 和 `treatment_id`。** 按第 3 节"实验单元"的规则得出，解析不了就留空并计数。
- **数值单位。** 一律是变量表里该变量的单位，不另起单位列。
- **`trigger` 去掉备注。**
  - 实现时先找出代码里所有写 `trigger` 的地方，列成一张允许的格式表。
  - `manual` 和 `manual: <备注>` 都导出为 `manual`；`planned irrigation <task_id>` 带或不带备注都导出为 `planned irrigation <task_id>`；其余系统格式按表原样导出。
  - 不在表里的值一律导出为 `other` 并计数。这样以后新增的格式即使带备注，也不会漏出去。
  - 备注原文不出现在任何文件里。
- **`withheld.csv`。**
  - 列出导出时整个项目生效的留出声明：每个留出的每个批次的每个结果变量。
  - 它说明的是"这些批次的这些变量按设计不给"，而不是"这份文件里删掉了哪些行"。所以不管结果是在冻结时还是在导出时被排除的，都在这里；某个批次也未必出现在本次实验里。
  - 结果字段无法解析的留出，`variable_id` 写 `*`。
  - 结果的值不出现在任何文件里。这张表让训练流程把这些空缺当作"有意拿掉"，而不是随机缺失。

## 9. 留出：在导出时重新过滤

快照冻结时套用的是**冻结那一刻**的留出登记。正常流程里留出在开发之前登记，结果行在冻结时就已排除，快照里只剩一个计数。但如果留出是在冻结之后才登记的，那份快照里就还带着如今该被留出的结果。

因此导出时对测量行**再套一次**当前的 `development_filter(project_id)`，被过滤掉的行不写进 `measurements.csv`。冻结时排除的行数（清单里的 `measurements_excluded`）和导出时排除的行数分开记进元数据。`withheld.csv` 的内容直接取自当前留出登记，不依赖哪一步排除了哪些行（见第 8 节）。这是本设计里最重要的一条，单独测试。

留出批次的传感器数据、设备状态和非结果测量照常导出：留出只拿掉结果，不拿掉特征。

## 10. 操作员假名

- 导出里所有 `operator` 列写的都是假名，格式为 `op-` 加 `HMAC-SHA256(key, 操作员名)` 的前 12 个十六进制字符。
- `key` 是 32 字节随机数，存放在 `<数据目录>/export/pseudonym.key`，权限 0600，第一次导出时生成，不写进任何导出，也不写进日志。
- 同一套安装导出的多个快照中，同一个人的假名相同，所以训练方能把"谁测的"当协变量，但看不到是谁。删掉 key 后，新导出的假名和旧导出对不上，wiki 里写明这一点。
- 真名和操作员备注不出现在导出目录的任何文件里，用测试钉住。

## 11. `croissant.json`

- `@context` 用 Croissant 1.1 的标准上下文，加上第 5.1 节白名单里的前缀，以及 `prov`。
- **数据集必填项：**
  - `name`：`diagri-<快照 ID>`。
  - `description`：由协议的研究问题和假设生成。
  - `license`、`creator`：来自命令参数。
  - `url`：用 `--url`；不给时用 `urn:diagri:snapshot:<快照 ID>`。
  - `datePublished`：快照的冻结日期，而不是导出当天，保证可复现。
  - `version`：快照版本。
  - `conformsTo`：`http://mlcommons.org/croissant/1.1`。
- `about`：`{"@id": "NCBITaxon:…"}`，即协议的 `crop_taxon`。
- `distribution`：每个 CSV 一个 `FileObject`，带 `contentUrl`（相对文件名）、`encodingFormat: text/csv` 和 `sha256`。
- `recordSet`：
  - 每张表一个，每列一个 `Field`，带 `dataType`（`sc:Text`、`sc:Float`、`sc:Integer`、`sc:Boolean`、`sc:DateTime`）。
  - `variable_id` 列用 `references` 指向 `variables.csv` 的 `variable_id`（它是该表的键）。`treatment_id` 和 `unit` 不用 `references`，只在字段描述里写明来源：`treatments.csv` 每个处理每个因子一行，`unit` 的键是 `round` 与 `unit` 合起来；按非键列做连接会让记录成倍增加。
  - 变量表的 `refs` 字段在描述里写明"以空格分隔的 CURIE，前缀见 `@context`"。
  - 设备状态表的 `key` 字段在描述里列出每个键的含义。
- **溯源：**
  - `prov:wasDerivedFrom` 指向快照（快照 ID 和清单 sha256）；
  - `prov:wasGeneratedBy` 描述这次导出：软件名 `growbridge`、版本号、命令名。
- **其余 DiAGRI 信息**用 schema.org 标准的 `additionalProperty`（`PropertyValue`，含 `name` 和 `value`，有本体术语时再带 `propertyID`）表达，不自造命名空间：
  - `cultivar`；
  - 设施类型（可控环境生长帐篷），有核对过的术语就带上，没有就只写文字；
  - 快照的目录版本和导出时的当前目录版本；
  - 快照的覆盖率和缺口；
  - 第 7 节列出的各项计数；
  - 冻结后被更正的记录 ID。

## 12. 退役 `export_miappe`

- 删除 `archive/export.py` 和它的测试。第一阶段只为它修过一个传感器键的 bug，没有别的调用方。
- 新代码放在独立的包 `growbridge/dataset/` 里，按职责分文件：读取和过滤、各表的行、Croissant 元数据、假名。
- 更新 wiki（中英文）：
  - `Data-Archive-and-Traceability`：删去 `export_miappe` 的段落，改为介绍新命令；
  - `Variable-Catalog`：加入术语填写流程和 `unit_refs`；
  - 新增一页"训练数据集导出"，说明命令、各表、设备状态各键的含义、留出、假名和 key 的作用、备注不导出。

## 13. 测试

- **金样。** 一个小的夹具快照，覆盖：
  - 两轮实验，其中一轮有两个单元；
  - 一条更正链；
  - 一个卡值时段；
  - 一个无采集时间的样本；
  - 一个无法解析的设备键；
  - 带灯、风扇和插座状态的样本，以及一个非数值的设备状态叶子；
  - 一个手动动作和一个计划灌溉动作，各带一条备注；
  - 一个留出批次。

  导出的每个文件与仓库里的预期文件逐字节相同；连续导出两次结果相同。
- **能被读取。** `mlcroissant`（加进 `dev` 可选依赖，固定版本）加载 `croissant.json`，逐行读出每个 recordSet，行数与 CSV 一致。
- **冻结前登记的留出。** 正常流程：先登记留出，再冻结，再导出。结果行不在 `measurements.csv` 里，`withheld.csv` 列出该留出的批次和变量，元数据里"冻结时排除"的计数等于清单的 `measurements_excluded`。
- **冻结后登记的留出。** 先冻结快照，再登记留出，然后导出：结果行不在 `measurements.csv` 里，`withheld.csv` 列出它们，"导出时排除"的计数正确。
- **整批隐藏。** 留出的结果字段有一个无法解析时，该批次的全部测量都不导出，`withheld.csv` 中 `variable_id` 为 `*`。
- **没有真名和备注。** 夹具里的备注包含操作员名和一段特定文字；在导出目录的所有文件里搜索操作员名和这段文字，一处都不能有。假名在两个快照之间一致。
- **未知的触发格式。** 一个不在允许表里的 `trigger` 值导出为 `other`，并计入计数。
- **拒绝的情况。** 第 7 节列出的每一种都有一个测试。
- **不写存档。** 导出前后数据目录里除假名 key 以外没有文件发生变化。
- **协议。** 新字段为空时摘要等于钉住的值；`crop_taxon` 格式不对时拒绝，并带登记过的 reason。
- **目录。** CURIE 格式错误或前缀不在白名单里时抛 `CatalogError`；`unit_refs` 的键必须是用到的单位，值必须是 `UO:` 前缀。

## 14. 上线顺序

1. **目录格式。** CURIE 校验、前缀白名单、`unit_refs`。此时 `refs` 仍为空，`version` 不变。
2. **协议字段。** `crop_taxon`、`cultivar`、保存检查、拒绝理由和中英文提示、控制台表单。
3. **导出包和命令。** 包括测试，并删除 `export_miappe`。
4. **填术语。** 按第 5.2 节，用户逐条确认后写入，`version` 变为 2。这是唯一需要人参与的一步，可以和第 3 步并行准备。
5. **文档。** wiki 中英文。

## 15. 留给实现者

- `growbridge/dataset/` 内的具体文件划分和函数名。
- 命令行如何找到快照对应的协议版本和轮次，只要与报告的做法一致。
- `mlcroissant` 的具体版本。如果它不接受 `urn:` 形式的 `url`，改为要求必须给 `--url`，并在本文记下。
- CSV 写出的细节，只要满足第 8 节的格式规则。
- `trigger` 允许格式表的具体内容，以代码里实际写 `trigger` 的地方为准。

## 16. 最容易出问题的地方

1. **冻结后才登记的留出。** 只信任快照的过滤，就会泄漏。见第 9 节。
2. **时间对齐。** 混用采集时间和接收时间而不加标记，模型学到的会是设备时钟的误差。见第 8 节的 `time_source`。
3. **卡值的传感器。** 一个卡住的读数看起来完全正常，只有 `frozen_periods` 知道它不可靠。见 `stuck` 列。
4. **人写的自由文本。**
   - 操作员备注藏在动作的 `trigger` 里，按第 8 节去掉；新增的触发格式默认归为 `other`，不会漏出备注。
   - 测量的 `batch`、`plant_id`、`position`、`layout_version` 和协议的研究问题、假设仍然原样导出，它们是数据的一部分。本设计不做自动清洗，wiki 提醒录入者不要在这些地方写人名。
5. **数值格式的确定性。** 浮点写法、行序、JSON 键序，任何一处不固定，"逐字节相同"就会失效。见金样测试。

## 17. 设计时自行决定的事项

以下几条用户没有直接说过，是写设计时按"不泄漏、不靠猜、不悄悄丢行"的原则定的，审阅时请重点看：

1. **导出时按当前留出登记再过滤一次**（第 9 节），而不是只信任快照冻结时的过滤。
2. **`withheld.csv` 列的是留出声明，而不是被删的行**（第 8 节）。这样正常流程下它也不会是空的。
3. **导出设备自身状态，但不进目录**（第 8 节）。它们是这台控制器特有的量；跨来源对齐靠 PPFD 等传感器。
4. **操作员假名用本机密钥做带密钥的哈希**（第 10 节）：跨快照一致，但看不出是谁。
5. **`trigger` 只保留触发来源，备注原文一律不导出**（第 8 节），未知格式归为 `other`。
6. **`crop_taxon` 在保存协议时必填**（第 6 节），而不是等到导出时才发现缺失。
7. **CSV 而不是 Parquet**，不增加运行时依赖；**`datePublished` 用快照冻结日期**，保证逐字节可复现。
8. **本体术语由实现者先查候选，用户逐条确认后才写入**（第 5.2 节）。
