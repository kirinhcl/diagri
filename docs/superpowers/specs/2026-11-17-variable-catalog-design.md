# 变量目录（受控词表）：设计

**日期：** 2026-11-17 · **状态：** 草稿，待批准（已按审阅意见修订） · **分支（建议）：** `feat/variable-catalog`

## 1. 意图

DiAGRI 里"测的是什么量、用什么单位"全是自由字符串，不同模块之间靠字符串完全相等联系起来。这带来五个问题，前三个会让内部数据悄悄出错：

1. **分析会悄悄少数据。** 统计按 `item.metric == metric` 挑测量（`research/stats.py:58`），`metric` 就是协议里的 `primary_endpoint` 字符串。测量录入接口不检查 metric 和 unit（`workbench/api.py:457`），表单里这两项是自由文本框（`web/workbench/pages/stage-measurements.js:56-58`）。名字打错一个字母，这条测量就不进分析，也不报错。
2. **holdout 盲法会泄露。** 留出批次按指标名屏蔽结果：`if measurement.metric not in outcome_fields: continue`（`research/holdout.py:217`）。留出批次里一条名字打错的结果不会被屏蔽，agent 能看到本该对它隐藏的数据。
3. **单位混用发现得太晚。** 统计在单位混用时会报错（`stats.py:59`），但那时数据已经录完，可能是几周以后。
4. **湿度判断靠子串。** `_is_humidity` 用 `"humi" in name or name == "rh"`（`planning/validate.py:118`）。它背后是一条安全规则：湿度反馈只能动排风。换一个设备、键名不同，就会漏检。
5. **对外导出缺信息，还有一个 bug。** `miappe.json` 里传感器变量写的是 `"unit": None, "method": "sensor reading"`（`archive/export.py:35`），所有变量都没有本体引用。MIAPPE 要求观测变量有 trait、method、scale 和本体术语。而且导出的"传感器变量"取的是样本 `data` 的顶层键（`export.py:32`），也就是 `sensor`、`outlet`、`light`、`blower`、`fan`；真正的传感器读数在 `data["sensor"]` 下面（`control/device.py:76`）。

**用户的决定：**

- 两件事都要做，先保证内部数据不出错，再做对外 FAIR 导出（用户原话："两个都要，先保证内部数据不出错"）。第一阶段解决问题 1–4，第二阶段解决问题 5。
- 做法选"共享变量目录 + 协议引用"（用户选择："方案三"），见第 4 节。
- 真机上还没有 DiAGRI 实验数据（用户回答："还没有"）。所以不做旧数据迁移：没有审计命令，没有为旧名字设的别名，所有检查从第一天起全部生效。

**我的判断（可以改）：**

- 目录是随代码发布的文件，修改走 git 审阅，不做 workbench 编辑界面（已在对话中提出，用户没有反对）。
- 开发库和模拟数据里已有的记录一条不改，也不去清理。遇到解析不了的名字，按第 8 节的兜底规则处理。
- 只有传感器条目可以有别名，别名就是设备键名。手工变量和处理因子没有别名（5.1）。
- 新协议必须声明变量。一个实验的协议都没有声明变量时，录入一律拒收（第 6、7 节）。
- 弃用：新协议不能新引用已弃用的变量；同一协议的新版本可以保留它已经声明过的已弃用变量；录入接受协议声明过的已弃用变量（5.2、第 6、7 节）。这样进行中的实验不会被迫中途换变量。
- holdout 遇到解析不了的名字，过滤时按"留出"处理，登记时按"已有结果"处理，都是拿不准就屏蔽（第 8 节）。
- 冻结的确认性分析脚本不加解析层，靠"手工记录只存标准 ID、ID 永不改"保证它看到的名字稳定（第 8 节）。
- 第一阶段不检查测量记录里的 `method` 字段，表单用目录里的方法预填（第 7 节）。

## 2. 目标、非目标、反目标

**目标**

- G1 新录入的手工测量：变量名必须是该实验的协议声明过的标准 ID，单位必须是该变量的标准单位。
- G2 新保存的协议：声明的变量、主终点、处理因子键，都必须能在目录里找到。
- G3 所有按变量名比较的地方（统计、报告、快照、holdout 过滤、holdout 登记）改为按解析后的 ID 比较。holdout 遇到解析不了的名字，一律屏蔽。
- G4 快照带上本实验用到的变量定义，一年后仍能知道每个名字当时是什么意思。
- G5 湿度判断同时参考目录，结果只会更严，不会更松。
- G6（第二阶段）`miappe.json` 里每个观测变量都有单位、方法和本体引用，传感器变量也一样，并且取的是真正的传感器键。

**非目标**

- workbench 上的目录编辑界面。
- 在线查询本体服务（OLS、AgroPortal）、OWL 推理、图数据库或 RDF 库。
- 单位换算。录入时单位不对就拒收，不自动换算。
- 修改设备侧。`Capabilities.sensors` 的键名和单位字符串不动，因为它们参与能力版本的哈希（`control/device.py:63`）。
- 约束 agent 的工具 schema。协议和测量都是人写的，agent 不写。
- 旧数据迁移工具（审计命令、批量更正）。真机上还没有数据。
- 证据卡单位检查、生育期标准化（BBCH）、ISA-JSON / BrAPI / RO-Crate 导出。这些在第二阶段之后再说。

**反目标**（技术上能跑，但算失败）

- 修改了任何已存的原始记录或已存的协议版本。
- 已存协议重新计算出的 digest 变了。
- 目录加载失败时静默跳过检查。必须启动失败或拒收。
- 湿度判断因为目录变得更宽松。
- 录入被拦下，但操作员不知道该怎么改。错误信息必须给出应该用的标准 ID 和单位。

## 3. 约束（来自现有代码）

- **digest 包含默认值。** `Model` 是 `frozen=True, extra="forbid"`，`digest()` 是 `content_digest(self.model_dump(mode="json"))`（`archive/models.py:26-30`）。给 `ResearchProtocol` 加一个带默认值的字段，所有已存协议重新计算出的 digest 都会变。写入时的 digest 存在 `wf_protocols` 里（`workflow/store.py:166`），workbench 保存协议后会返回 digest（`workbench/rounds.py:209`），`save_protocol` 也用 digest 判断同一版本内容是否相同（`workflow/service.py:110`）。所以新字段为空时，不能出现在 dump 里。
- **不能用 `Field(exclude_if=...)`。** 开发环境装的是 Pydantic 2.14，但 `pyproject.toml:12` 只要求 `pydantic>=2,<3`。`exclude_if` 只有较新的 2.x 才支持，老版本会把它当成多余参数忽略、不报错，digest 就会悄悄变掉。代码里已经有现成的写法：`ManualTask` 用 `model_serializer(mode="wrap")` 在字段为空时把它从 dump 里去掉（`archive/models.py:278-285`），所有 2.x 版本行为一致。
- **协议版本不可变。** 改协议只能升版本（`service.py:110-112`）。`save_protocol` 只查同一 id、同一版本的已存协议（`service.py:106`）。
- **一个实验可能对应多个协议版本。** `store.protocol_versions_of(experiment_id)`（`store.py:369`）返回该实验所有轮次的协议版本。
- **测量只有一个写入口。** 手工测量只在 workbench 的 `POST /measurements` 创建（`api.py:457-471`）。更正是写一条新记录，用 `corrects` 指向原记录，原记录不改。**写入更正时，包含原记录的快照和由它们生成的报告会被标为无效**（`archive/store.py:334-340`，`mark_dependents_invalid`）。
- **配置格式。** 配置文件是 TOML，用标准库 tomllib 读（`config.py:3`），项目没有 YAML 依赖。随包发布的非 Python 文件在 `pyproject.toml:25` 的 package-data 里登记。
- **快照格式。** 快照是一组 jsonl 文件加上记录哈希的 manifest（`archive/snapshot.py:90-98`）。导出只读快照里的文件，不读在线数据库（`export.py` 文件头注释）。
- **holdout 在三个地方生效，用的是同一个函数。** `HoldoutRegistry.development_filter` 返回 `keep`（`research/holdout.py:204-221`）。agent 用的开发快照在冻结时就用它排除留出行，manifest 只记被排除的条数（`agents/handlers_researcher.py:133`、`agents/handlers_planner.py:95`）；读快照时 `refuse_holdout_rows` 再用它检查一遍，只要有一行不该出现，就拒绝整份快照（`holdout.py:261-275`）。
- **登记 holdout 前的检查。** `archive/store.py:352-370` 的 `outcome_experiments` 用 SQL `json_extract(body, '$.metric') IN (...)` 查哪些实验在这些批次里已经有这些结果字段的数据，被更正过的记录也算（由 `runtime.py:676` 接入）。SQL 里没法解析名字。
- **冻结的确认性分析脚本。** 阶段开始后脚本就不能再冻结或修改（`workbench/analysis.py:84`）。脚本在沙箱里自己读快照的原始 `measurements.jsonl`，自己按 metric 字符串筛选，平台没法在中间加一层解析。
- **设备传感器。** 真机传感器表（`control/device.py:23-30`）：`temp` C、`humi` %、`vpd` kPa、`co2` ppm、`ppfd` umol/m2/s、`tempSoil` C。样本里传感器读数在 `data["sensor"]` 下面（`device.py:76`），`data` 的顶层键是 `sensor`、`outlet`、`light`、`blower`、`fan`。模拟器只有 `temp` 和 `humi`（`sim/control.py:81`）。
- **workbench 表单。** 协议表单是预填好的 JSON 模板（`web/workbench/pages/project-forms.js:17-28`，模板里有 `factors: { light: 40 }` 和 `primary_endpoint: "canopy_area_growth"`）。

## 4. 方案

讨论过三种做法：

| 做法 | 内容 | 取舍 |
|---|---|---|
| 一、全局词表文件 | 一个文件列出所有变量。录入、终点、holdout 都只能使用其中的 ID | 最简单，不同实验天然一致。但只能保证"名字存在"，挡不住"录了一个合法但本实验不测的变量" |
| 二、协议内声明变量 | 每个协议版本自己定义要测的变量和单位 | 检查最严，和实验绑定，可复现性跟着协议走。但同名变量在不同项目里可能定义不同，做 FAIR 时要逐个协议去对接本体 |
| **三、共享目录 + 协议引用（已选）** | 共享目录定义变量，协议从目录里选出本实验要测的变量 | 录入检查和方案二一样严，跨实验和方案一一样一致。代价是多一个目录文件，协议多一个字段 |

选方案三的原因：协议保存后不能修改，现在定下的变量引用格式，会写死在以后每一个协议版本里。如果先走方案二、以后再补共享目录，已有协议里的变量就永远是各自定义的。

## 5. 变量目录

### 5.1 文件和字段

目录文件是 `src/growbridge/vocab/catalog.toml`，登记进 package-data。示例（下面的数值只是格式示例，不是最终内容）：

```toml
version = 1

[unit_aliases]          # 设备单位写法 → UCUM 代码，只用于比较设备单位
C = "Cel"
ppm = "[ppm]"

[[variable]]
id = "air_temperature"
kind = "sensor"
label_en = "Air temperature"
label_zh = "气温"
quantity = "temperature"
unit = "Cel"
min = -50
max = 80
aliases = ["temp"]
refs = []

[[variable]]
id = "canopy_area_growth"
kind = "manual"
label_en = "..."
label_zh = "..."
quantity = "..."
unit = "..."
method = "..."
min = 0
refs = []
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 匹配 `^[a-z][a-z0-9_]{1,62}$`，发布后不再改变 |
| `kind` | 是 | `manual`、`sensor` 或 `factor` |
| `label_en`、`label_zh` | 是 | 显示名称 |
| `quantity` | 是 | 物理量，取值来自代码里的一个小枚举（比如 temperature、relative_humidity、area、concentration、level、count） |
| `unit` | 是 | UCUM 代码 |
| `method` | `manual` 必填 | 测量方法的文字描述 |
| `min`、`max` | 否 | 物理上不可能超出的界限（比如面积不能为负，相对湿度在 0–100），超出就拒收。这不是"看起来可疑"的范围 |
| `aliases` | 否 | 设备键名。只有 `kind = "sensor"` 的条目可以有（我的判断）。手工变量和处理因子没有旧名字要兼容；以后要改名，就新建 ID 并弃用旧的 |
| `deprecated`、`replaced_by` | 否 | 弃用标记，以及替代它的条目 |
| `refs` | 否 | 本体 CURIE 或 IRI，第二阶段再填 |

### 5.2 只追加规则

- **定义字段**（`id`、`kind`、`quantity`、`unit`、`method`、`min`、`max`）发布后不再修改。要改含义，就新建一个 ID，把旧条目标为 `deprecated`，并填上 `replaced_by`。
- **可以改的**：标签、给传感器条目追加 `aliases`、追加 `refs`、把 `deprecated` 设为真。
- 每次修改，`version` 加 1。
- 用测试强制执行。一个提交到仓库的 `catalog.lock.json` 记录每个条目定义字段的哈希，测试逐条比对：已有条目的哈希变了就失败；新条目必须同时加进 lock。
- 别名在整个目录里唯一，不能和任何 `id` 重名，只能出现在传感器条目上，同样由测试检查。
- 弃用不影响已经在用的地方：声明过某个变量的协议，它的新版本可以继续声明它，录入也继续接受（第 6、7 节）。只有新协议不能新引用它。

有了这条规则，任何时候用最新的目录去解析一个旧 ID，结果都和当初一样。所以协议里不需要记目录版本。

### 5.3 加载和解析

- 启动时加载一次。格式错误、ID 重复、别名冲突、`replaced_by` 指向不存在的条目，都会让启动失败，错误信息要指出是哪一条。
- 对外提供 `Catalog` 对象，包括 `resolve(name) -> Variable | None`、`get(id)`、`version`，以及 `digest`（文件字节的 sha256）。
- **`resolve` 的规则：** 先按 `id` 精确匹配，再按别名精确匹配，都不中就返回 None。区分大小写，不做任何模糊匹配，因为"差不多就算对"正是要消除的问题。已弃用的条目解析到它自己，不会跳到替代条目，因为两者含义不同。
- `Catalog` 由 runtime 构造，再传给用到它的地方（workbench、holdout、统计和报告的调用方、运行单校验）。

### 5.4 首批内容

- 真机的 6 个传感器，各自把设备键名作为别名。
- 测试夹具里用到的名字（`canopy_area_growth`、`light`）。夹具里的协议同步加上 `variables`。
- 第一个真实实验要测的手工变量和处理因子，由研究者在实验开始前加进目录。这部分内容只有研究者能定。
- 第一阶段 `refs` 全部留空。

## 6. 协议引用变量

`ResearchProtocol` 新增一个字段，并照抄 `ManualTask` 的写法（`models.py:278-285`），在它为空时从 dump 里去掉：

```python
class ResearchProtocol(Model):
    ...
    variables: tuple[str, ...] = ()

    @model_serializer(mode="wrap")
    def _without_empty_variables(self, handler):
        data = handler(self)
        if isinstance(data, dict) and not data.get("variables"):
            data.pop("variables", None)
        return data
```

为空时不出现在 dump 里，所以已存协议的 digest 不变。需要一个"黄金测试"来保证这一点。第二阶段的 `crop_taxon` 也放进同一个序列化器。

**保存新协议版本时检查。** 检查放在 `service.save_protocol` 写入之前；如果同一版本已存在且 digest 相同，照旧直接返回，不检查：

1. `variables` 不能为空。
2. 每个变量都必须按 `id` 命中目录（按别名命中不算），错误信息里给出对应的标准 ID。已弃用的 ID，只有在同一协议 id 的较早版本已经声明过它时才接受；否则拒收，并提示 `replaced_by`。
3. 变量不能重复。
4. `analysis.primary_endpoint` 必须在 `variables` 里。
5. 每个 `Treatment.factors` 的键，都必须是目录中 `kind = "factor"` 的标准 ID。

检查不通过时一次性列出全部问题，用现有的 `Denied` 拒绝。workbench 的协议模板（`project-forms.js`）同步加上 `variables`，因子键也改成目录里的 ID。

## 7. 录入检查

新增函数 `check_measurement(record, catalog, declared) -> list[str]`，`declared` 的类型是 `frozenset[str]`。workbench 的 `POST /measurements` 在 `archive.add_measurement` 之前调用它；有问题就返回 422，并列出全部问题。

`declared` 是该实验所有协议版本（`protocol_versions_of`）声明的变量的并集。

**规则：**

1. `declared` 为空（这个实验的协议都没有声明变量），拒收，提示先给协议升一个版本并声明变量。
2. `metric` 必须按 `id` 命中目录，并且在 `declared` 里。错误信息列出 `declared` 里的变量。
3. 该变量的 `kind` 必须是 `manual`。
4. `unit` 必须和该变量的 `unit` 完全一致。
5. 数值不能超出 `min`/`max`。
6. 已弃用的变量照常接受。它能出现在 `declared` 里，说明这个实验在弃用之前就声明了它。
7. 更正记录（设置了 `corrects`）走同样的检查。更正记录的 `metric` 可以和原记录不同。按现有设计，写入更正会让包含原记录的快照和报告作废（`store.py:334-340`）。

**表单改动。** `stage-measurements.js` 里，metric 改成下拉框，选项是 `declared` 里的变量，显示当前语言的标签。`declared` 为空时，表单显示原因并禁用提交。unit 根据所选变量自动填入，不能编辑；method 预填。新增一个只读接口 `GET /experiments/{experiment_id}/variables`，返回 `declared` 里每个变量的 `id`、标签、`unit`、`method`、`min`、`max` 和是否已弃用。

表单负责让人不容易填错，接口负责确保填错了也进不来，两者都要有。

## 8. 按 ID 比较

用一个函数 `canonical(name, catalog) -> str | None` 取代所有字符串比较。如何处理 None，由调用方自己决定：

| 位置 | 改法 | 遇到 None |
|---|---|---|
| `research/stats.py:58` | 按 `canonical(item.metric) == canonical(metric)` 筛选 | 只和完全相同的原始字符串匹配，不和其他名字合并；报告里列出解析不了的名字有几个 |
| `agents/handlers_report.py:135, 161`（以及 299、360 取终点的地方） | 同上 | 同上 |
| `archive/snapshot.py:214` 按 metric 分组 | 按 canonical ID 分组 | 用原始字符串单独成组 |
| `research/holdout.py:217`，`keep` 的留出判断 | 按 canonical ID 比较 | **视为留出**：留出批次里解析不了的名字一律屏蔽。这和现有规则"没有批次号的测量视为留出"（`holdout.py:208`）是同一个思路 |
| `archive/store.py:352-370`，`outcome_experiments`（登记 holdout 前的检查） | SQL 只按批次筛出候选测量的 `(experiment_id, metric)`，名字放到 Python 里解析 | **视为已有结果**：登记被拒绝，错误信息列出这些名字 |
| `workbench/holdouts.py:64` 登记留出 | 每个 `outcome_fields` 都必须能解析，否则拒绝登记。存储时保持原样，比较时再解析 | 拒绝登记 |

**下面两处不用改，但行为会跟着变或者需要说明：**

- **快照的冻结和读取。** 冻结开发快照和 `refuse_holdout_rows` 用的都是 `keep`（第 3 节）。`keep` 改了以后，新冻结的开发快照会自动排除留出批次里名字解析不了的行；以前冻结的、含有这种行的快照，读取时会被整份拒绝。这是有意的。真机上没有数据，受影响的只有开发库里的快照。
- **冻结的确认性分析脚本（`workbench/analysis.py`）。** 平台不改。它们看到的名字是稳定的：手工测量只能通过录入接口写入，接口只收标准 ID；手工变量没有别名；ID 永不改。所以同一个手工变量在 `measurements.jsonl` 里永远只有一种写法。wiki 里写明脚本应按变量 ID 筛选。

`stats.py:59` 的单位混用报错保留。通过录入接口写入的数据不会触发它，因为每个变量只接受一个单位；如果触发，说明数据来自绕过接口的写入（脚本、模拟器）或开发库里的旧数据。它是最后一道防线。

## 9. 快照

快照新增一个文件 `catalog.json`，用 canonical_json 写出，并记进 manifest：

```json
{
  "version": 3,
  "digest": "<catalog.toml 的 sha256>",
  "variables": [ /* 本实验用到的变量的完整条目，按 id 排序 */ ],
  "unresolved": [ /* 解析不了的名字，排序 */ ]
}
```

"本实验用到的变量"包括三部分：本实验各协议版本声明的变量、测量记录里出现的 metric、样本 `data["sensor"]` 下出现的键。

开发库和测试里已有不带这个文件的快照，读快照的代码必须能处理它不存在的情况。

## 10. 运行单校验：湿度

`_is_humidity(rule)` 改成两者取或：`catalog.resolve(rule.sensor)` 的 `quantity` 是 `relative_humidity`，**或者**现有的子串规则成立。这样结果只会更严。

`validate_run_sheet` 需要拿到目录。调用方有两处：`runtime.py:657` 和 `agents/handlers_common.py:86`。具体怎么注入，留给实现者决定。`unit_mismatch` 在第一阶段不变。

## 11. 第二阶段：FAIR 导出

第一阶段上线之后再做：

1. **填 `refs`。** 在 OLS 或 AgroPortal 上逐条人工查询后填入：手工性状用 Crop Ontology 的 variable / trait / method / scale，处理因子用 PECO，单位用 UO，环境量用 ENVO 或 AgrO。每次添加都让 `version` 加 1。不确定的条目宁可留空，也不要猜。
2. **加作物分类。** `ResearchProtocol` 新增可选字段 `crop_taxon`（NCBITaxon 的 CURIE），放进第 6 节的同一个序列化器，为空时去掉。
3. **改导出。** `export.py` 的 `observed_variables` 改为从快照的 `catalog.json` 生成，包括 id、标签、quantity、单位、方法和 refs，传感器变量也有单位。
   - 传感器变量取样本 `data["sensor"]` 下的键。现在 `export.py:32` 取的是 `data` 的顶层键，其中 `light` 还会和处理因子 ID `light` 撞名。这个 bug 不必等第二阶段，可以单独先修。
   - 定义字段来自快照。
   - `refs` 取自当前目录。因为定义字段不可变，这样做是安全的。导出时同时记下快照里的目录版本和当前目录版本。
   - 没有 `catalog.json` 的快照，照现在的方式导出。

## 12. 上线顺序

1. **目录、加载器、lock 测试和首批条目**（第 5 节）。
2. **改为按 ID 比较**（第 8 节）。
3. **协议检查和模板**（第 6 节），测试夹具同步加上 `variables`。
4. **录入检查、表单和接口**（第 7 节）。
5. **快照里的 `catalog.json`**（第 9 节）。
6. **湿度规则**（第 10 节）。
7. **第二阶段导出**（第 11 节）。

真机上还没有数据，第 1–6 步可以一起上线，不需要过渡期。唯一的前提是：第一个真实实验开始之前，它的变量已经在目录里（5.4）。

## 13. 测试

- **目录：** 格式错误、ID 重复、别名冲突、别名出现在非传感器条目上、`replaced_by` 悬空，都会导致加载失败；lock 测试能抓到已有条目定义字段被修改；`resolve` 的精确匹配和弃用条目的行为；真机传感器表（`device.py:23-30`）里每个键都解析到一个传感器条目，设备单位经 `unit_aliases` 换成 UCUM 后和条目单位一致。
- **digest 黄金测试：** 一个不带 `variables` 的协议 JSON，加载后算出的 digest 和改动前的固定值一样。
- **协议保存：** 第 6 节的五条规则各有一个拒收用例；新协议引用已弃用变量被拒收，同一协议的新版本保留已声明的已弃用变量可以通过；同版本同内容重复保存照旧返回，不做检查。
- **录入：** 第 7 节的规则各有用例；`declared` 为空时拒收；实验跨多个协议版本时取并集；协议声明过的已弃用变量可以录；更正记录可以改 metric。
- **holdout 泄露回归测试：** 留出批次里有一条 metric 打错的测量。改动前它会被 `keep` 保留，改动后必须被屏蔽。
- **holdout 登记：** 留出批次里有一条名字解析不了的测量时，登记被拒绝，错误信息列出这个名字。
- **快照与 holdout：** 冻结开发快照时，留出批次里名字解析不了的行被排除；含有这种行的旧快照被 `refuse_holdout_rows` 拒绝。
- **统计：** 解析不了的名字不和任何 ID 合并，报告里有计数。
- **快照：** `catalog.json` 的内容、排序和哈希都在 manifest 里，`unresolved` 列表正确，传感器键取自 `data["sensor"]`；不带这个文件的快照也能正常读取。
- **湿度：** 目录判断和子串判断取或，任一成立就阻断；目录判断不会让原本阻断的规则通过。
- **第二阶段：** 导出的变量带单位和 refs；传感器变量来自 `data["sensor"]`，不再出现 `outlet`、`light`、`blower`、`fan`；不带 `catalog.json` 的快照导出结果不变。

## 14. 文档

wiki 的中英文两版都要更新：

- 术语表加"变量目录"。
- 操作员录入说明：下拉框、被拒收时怎么办、怎么用更正记录修正，以及更正会让相关的快照和报告作废。
- 新的一页"如何新增变量"：只追加规则、lock 文件、版本号、弃用，以及第一个实验开始前要先把变量加进目录。
- 确认性分析脚本的说明里加一句：按变量 ID 筛选。

## 15. 留给实现者

- 模块布局（建议放在 `growbridge/vocab/` 下）。
- `Catalog` 的注入方式，包括 `validate_run_sheet` 拿到目录的方式。
- `quantity` 枚举的具体取值。
- 6 个传感器条目的标签和 `min`/`max`。
- `outcome_experiments` 改写后的具体 SQL。
- 错误信息的措辞，以及中英文 i18n 键。

## 16. 最容易出问题的地方

- **digest 漂移。** 用了 `exclude_if`，或者以后有人去掉第 6 节的序列化器，所有已存协议的 digest 都会变。黄金测试必须有。
- **holdout 登记放行。** `outcome_experiments` 如果还在 SQL 里直接比名字，解析不了的名字就会被漏掉，让登记在已有结果的情况下通过。名字必须拿出来解析。
- **holdout 会屏蔽得更多。** 解析不了的名字一律屏蔽，可能让 agent 能用的开发数据变少。这是有意的取舍：盲法比数据完整更重要。报告里要显示被这样屏蔽的条数，不能静默。
- **中途弃用。** 进行中的实验靠"同一协议的新版本可以保留已声明的已弃用变量"继续。如果实现时漏了这一条，研究者升协议版本时就会被迫换变量，同一个量的数据会分在两个 ID 下。
- **更正的代价。** 更正会让包含原记录的快照和报告作废。这是现有设计，但操作员要事先知道，所以写进 wiki。
- **两套单位写法。** `unit_aliases` 只用来比较设备单位。手工录入一律使用 UCUM 代码，不做别名映射，否则又回到"差不多就算对"。
