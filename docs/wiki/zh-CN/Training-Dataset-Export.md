# 训练数据集导出

[English](../en/Training-Dataset-Export.md)

这一页写给要把 DiAGRI 的数据拿去训练作物基础模型的人。它说明 `growbridge export-dataset` 从一个冻结快照写出什么：11 张 CSV 表和一份 Croissant 描述，每一列从哪里来，以及这些数字能说明什么、不能说明什么。命令的选项和退出码见 [CLI 参考](CLI-Reference.md#export-dataset)。

## 用途

一次导出对应一个实验的一个已校验快照，写成别的团队可以和其他来源的数据合并的形式。表是长格式（每个读数一行），所以多一个传感器键只多几行，不多列。时间一律是 UTC。输出里没有任何人名：操作员只以假名出现。

导出读的是快照自己的文件，所以带的是快照冻结时的内容。有三样东西来自当前的数据库而不是快照：协议和它的设计、现在的留出登记，以及冻结之后又被更正的测量清单。所有列的定义在 [`dataset/schema.py`](../../../src/growbridge/dataset/schema.py)，CSV 文件和 `croissant.json` 都从它生成。

## 命令写出什么

写进新建的目录 `--out`：

| 文件 | 每行是 |
| --- | --- |
| `variables.csv` | 数据用到的一个变量 |
| `treatments.csv` | 一个处理的一个因子 |
| `units.csv` | 一轮里的一个实验单位 |
| `sensor_readings.csv`、`sensor_readings_untrusted.csv` | 一个样本里的一个传感器键 |
| `device_states.csv`、`device_states_untrusted.csv` | 一个样本里的一个执行器状态键 |
| `measurements.csv` | 一次人工测量（每条取最新版本） |
| `actions.csv` | 一次执行请求 |
| `interventions.csv` | 一次干预 |
| `withheld.csv` | 一个被留出的批次和结局变量 |
| `croissant.json` | 以上所有文件的描述 |

文件先写到 `--out` 旁边的临时目录，全部写完再改名，所以失败的导出不会留下写了一半的目录。格式每次都一样：UTF-8，LF 换行，第一行是表头，时间是带毫秒和结尾 `Z` 的 UTC ISO 8601，空字段表示"无"，行按各表的键排序（[`dataset/csvfmt.py`](../../../src/growbridge/dataset/csvfmt.py)）。同一个快照、目录、留出登记、假名密钥和参数，得到逐字节相同的文件，前提是这期间没有为快照里的记录登记新的更正：`corrected_after_freeze` 读的是当前的档案而不是快照，这样的更正会改变 `croissant.json`。

### 不要用表格软件直接打开 CSV

CSV 文件是给机器读的训练数据，原样写出，不做任何转义。操作员录入的文本（`plant_id`、`batch`、`position` 等）没有针对表格公式做处理，以 `=`、`+`、`-` 或 `@` 开头的单元格可能被当成公式执行。不要用表格软件直接打开这些文件。用代码读取，或者导入表格软件时把每一列都设为文本。

## 各张表

列的类型是 `Text`、`Float`、`Integer`、`Boolean`（`true` 或 `false`）和 `DateTime`。值为空，或浮点数不是有限数时，字段为空。

### 传感器读数和设备状态

两对表开头的列相同：

| 列 | 含义 |
| --- | --- |
| `time` | 读数的时间。 |
| `time_source` | 设备在已同步的时钟上给出了采集时间时是 `captured`；否则是 `received`，即桥接收到读数的时间。 |
| `clock_synced` | 设备上报时它的时钟是否已同步。 |
| `sample_id` | 读数所属的样本；用来把读数分组。 |
| `device_id` | 产生读数的设备。 |
| `experiment_id`、`stage_id`、`round` | 读数落在实验的哪里；没有时为空。 |

`sensor_readings.csv` 另有 `variable_id`（该键对应的目录变量；没有时为空，并计入未解析的传感器键）、`raw_key`（控制器报告的原始键）、`value`（单位是该变量的 `unit_ucum`）、`quality`（控制器的质量标记；没有时为空）和 `stuck`。

`device_states.csv` 另有 `key`、`value` 和 `quality`。

**`time_source`。** 不看这一列就不要把两种时钟混用：接收时间含有设备到桥接之间的延迟，没有同步的设备时钟也不是可靠的时间。请按 `time_source` 和 `clock_synced` 过滤或建模，不要假定只有一种。

**`stuck`。** 读数落在该传感器一直报告完全相同数值的时段内（传感器卡住）时为真，依据是快照里的 `frozen_periods.jsonl`；尚未结束的时段一直算到最后。比较用的是样本的采集时间（设备给了采集时间就用它），冻结读数检查记录时段用的也是这个时间；即使时钟未同步、`time` 是接收时间，也是如此。这样的读数看起来正常，其实不可靠。

**可信与不可信。** 样本的时钟已同步、质量为 `ok`、来源为 `planned`，才算可信。可信样本进普通表，其余进 `_untrusted` 表，列相同；它们留作检查，不是训练数据。见[数据、档案与可追溯性](Data-Archive-and-Traceability.md#数据快照怎样冻结和校验)。

**不是数字的值。** 传感器或设备的值不是数字（文本、布尔值、空）时不成行，计入 `non_numeric_values`。样本的 `sensor` 值存在但不是对象时，不产生传感器行，计一次。不是有限数的数字（`nan`、`inf`）成行，但 `value` 为空。

### 设备状态的键

`key` 列是控制器报告的键，原样导出。各键的含义如下，来自 DiAGRI 发出的命令（[`mcp_server.py`](../../../src/growbridge/mcp_server.py)）。代码没有给单位，这里也不写单位。

| 键 | 取值 |
| --- | --- |
| `light.level` | 0 到 100：手动灯光亮度，按 DiAGRI 下达的 level 的刻度；0 为关。 |
| `fan.level` | 0 到 10：循环风扇的手动档位，按 DiAGRI 下达的 level 的刻度；0 为关。 |
| `blower.level` | 0 到 100：排风机的手动速度；0 为关。 |
| `light.on`、`fan.on`、`blower.on` | 0 或 1。 |
| `outlet.O1.on` 到 `outlet.O5.on` | 0 或 1。 |

### `variables.csv`

数据行引用到的每个变量一行，再加上协议声明的所有变量。条目取快照冻结时的那一份；本体相关的列取自现在的目录。

| 列 | 含义 |
| --- | --- |
| `variable_id` | 稳定的标识。 |
| `kind` | `sensor`、`manual` 或 `factor`。 |
| `label_en`、`quantity`、`method` | 英文名称、被测的量、测量方法（未指定时为空）。 |
| `unit_ucum` | UCUM 代码表示的单位。 |
| `unit_uo` | Units Ontology 术语表示的单位；确认前为空。 |
| `min`、`max` | 以 `unit_ucum` 计的合理范围；没有界限时为空。 |
| `refs` | 以空格分隔的本体术语 CURIE；确认前为空。 |
| `mapped` | `refs` 里至少有一个术语时为真。 |

未映射的变量照常导出，`mapped=false`，并计入 `unmapped_variables`。术语由研究者逐条确认后填入，见[变量目录](Variable-Catalog.md#本体术语)。

### `treatments.csv` 和 `units.csv`

`treatments.csv`：`treatment_id`、`name`、`is_control`、`variable_id`（因子）和 `value`（写成文本，因为因子的值可能是字符串）。有多个因子的处理有多行；没有因子的处理有一行，`variable_id` 和 `value` 为空。

`units.csv`：`round`、`block`（设计没有区组时为空）、`unit` 和 `treatment_id`，说明每个单位接受了哪个处理。它的键是 `round` 和 `unit` 合在一起。

### `measurements.csv`

`time`、`record_id`、`corrects`（本条更正的 `record_id`）、`experiment_id`、`round`、`batch`、`unit`、`treatment_id`、`plant_id`、`position`、`layout_version`、`variable_id`、`value`、`method` 和 `operator`。每个测量只有最新版本成行；被它取代的记录计入 `superseded_records`。`unit` 和 `treatment_id` 由位置通过协议里的设计得出。位置对不上任何单位时，`unit` 和 `treatment_id` 为空，并计入 `unplaced_measurements`。

测量的名称不在目录里，或单位和目录不一致时，整个导出被拒绝。

### `actions.csv` 和 `interventions.csv`

`actions.csv`：`request_id`、`channel`、`state`、`trigger`、`planned_level`、`confirmed_level`、`created_at`、`sent_at`、`confirmed_at`、`ran_seconds`、`error_code`、`ended_early_code`、`supersedes` 和 `operator`。`trigger` 经过清理，见[自由文本和人名](#自由文本和人名)。

`interventions.csv`：`id`、`time`、`stage_id`、`kind`、`detail`（系统记录的内容，JSON，键有序）和 `operator`。

### `withheld.csv`

`holdout_id`、`batch` 和 `variable_id`。见下一节。

## 留出不等于缺失

留出把某个批次的结局先扣下，留给以后检验模型（见[科研方法](Research-Methodology.md#预测模型与留出数据)）。在导出里，这些结局不出现在 `measurements.csv`，是有意设计的，不是随机缺失；`withheld.csv` 列出它们：每个被留出的批次和结局变量一行；留出集扣下全部结局变量，或写了目录解析不了的名称时，`variable_id` 为 `*`。出现在这里的批次，请当作在别处留作检验的数据，不要当作有缺失值的批次。

导出使用的是现在的留出登记，而不是快照冻结时的。快照冻结之后才登记的留出，结局同样不会进入导出；这样去掉的行计入 `withheld_at_export`，冻结时去掉的计入 `excluded_at_freeze`。被留出的只是结局：同一批次的传感器数据和非结局的测量仍然导出。

## 假名

每个 `operator` 的值都是 `op-` 加 12 个十六进制字符：用一个密钥对名字做 HMAC-SHA-256，再截短（[`dataset/pseudonym.py`](../../../src/growbridge/dataset/pseudonym.py)）。密钥是文件 `<data_dir>/export/pseudonym.key`，32 个随机字节，权限 0600，第一次导出时创建。这是导出唯一写进数据目录的东西。

- 同一个安装里，一个人在每次导出中都是同一个假名，所以可以跨导出跟踪同一个人。
- 无法从输出反查名字；没有密钥也无法重新算出假名。
- 删除密钥会切断这种关联：下一次导出会生成新密钥，每个人都得到新的假名，新旧导出无法再按 `operator` 连接。以后还要导出就保留密钥。密钥不属于数据集，不要分享。
- 守护进程的备份只复制数据库（[备份](Data-Archive-and-Traceability.md#备份)），不包括 `export/pseudonym.key`。从备份恢复的数据目录如果没有这个密钥，下一次导出里每个人都会得到新的假名。请另外备份密钥，并像密钥本身一样保管这份副本。

## 自由文本和人名

操作员的备注不导出。备注可能藏在动作的 `trigger` 里，所以对 trigger 做了清理：`manual` 和 `planned irrigation <id>` 两种触发后面的备注被去掉（计入 `notes_dropped`），清理器不认识的触发格式一律变成 `other`（计入 `other_triggers`），所以新的格式不会泄漏备注（[`dataset/triggers.py`](../../../src/growbridge/dataset/triggers.py)）。

有些自由文本本身就是数据，原样导出：`measurements.csv` 里的 `batch`、`plant_id`、`position`、`layout_version` 和 `method`，`treatments.csv` 里的处理名称 `name`，以及协议的研究问题和假设（它们构成 `croissant.json` 里的数据集描述）。没有任何程序清洗这些内容。**请提醒录入数据的人，不要在这些字段里写人名。**

## `croissant.json`

元数据遵循 Croissant 1.1，`conformsTo` 为 `http://mlcommons.org/croissant/1.1`，由 [`dataset/croissant.py`](../../../src/growbridge/dataset/croissant.py) 生成。

- **数据集字段。** `name` 是 `diagri-<快照 ID>`；`description` 是协议的研究问题和假设；`license` 和 `creator` 来自命令的 `--licence` 和 `--creator`（创作者记为 `sc:Organization`，这是 mlcroissant 接受的创作者写法之一，另一种是 `sc:Person`）；`url` 是 `--url`，缺省为 `urn:diagri:snapshot:<ID>`；`datePublished` 是快照创建时的 UTC 日期；`about` 是作物物种 `crop_taxon`。
- **文件。** 每个 CSV 一个 `FileObject`，带它的 SHA-256；每张表一个 `RecordSet`，每列一个 `Field`，带类型和描述。
- **引用。** 只有 `variable_id` 列带 Croissant 的 `references`，指向 `variables.csv`（`variable_id` 是它的键）。`treatment_id` 和 `unit` 改在字段描述里写明来源：`treatments.csv` 每个处理每个因子一行，`units.csv` 的键是 `round` 和 `unit` 合起来，按其中任何一个连接都会让记录成倍增加。
- **溯源。** `prov:wasDerivedFrom` 指向快照和它清单的 SHA-256；`prov:wasGeneratedBy` 写明 `growbridge`、它的版本和命令名。
- **计数。** `additionalProperty` 里有下面的计数，还有 `cultivar`、`facility_type`、快照的覆盖率和缺口、`snapshot_catalog_version`、`current_catalog_version`，以及 `corrected_after_freeze_ids`。

| 计数 | 含义 |
| --- | --- |
| `unmapped_variables` | `variables.csv` 里 `mapped=false` 的行数。 |
| `unresolved_sensor_keys` | 键解析不到任何目录变量的传感器行数。 |
| `non_numeric_values` | 不是数字、因此不成行的传感器和设备值的个数。 |
| `excluded_at_freeze` | 快照冻结时被去掉的结局测量。 |
| `withheld_at_export` | 现在被留出登记去掉的测量。 |
| `superseded_records` | 在快照中被更正取代的测量。 |
| `corrected_after_freeze` | 冻结之后又被更正的快照测量；导出里是冻结时的值。 |
| `notes_dropped` | 从 trigger 里去掉的操作员备注。 |
| `other_triggers` | 导出为 `other` 的 trigger。 |
| `unplaced_measurements` | 位置对不上任何单位的测量。 |

## 作物物种

`croissant.json` 通过协议写明作物。新的协议版本必须把 `crop_taxon` 写成 `NCBITaxon:<数字>`，即 NCBI Taxonomy 的编号；`cultivar` 可选，最多 200 个字符。不符合的版本保存时会以 `protocol_crop_taxon_invalid` 被拒绝，工作台的协议表单有这两个字段。更早保存的协议没有物种，无法导出；下一轮请用新版本。

## 只读，以及什么时候拒绝

导出只读取 archive、workflow 和 agents 三个数据库和快照目录，除假名密钥外不向数据目录写任何东西（后面的检查拒绝导出时，密钥可能已经存在）。它不拿守护进程锁，所以守护进程运行时也能导出。数据目录的结构比已安装的 growbridge 旧时、缺少数据库文件时、数据库正忙时、SQLite 读不了某个数据库时，它会拒绝并给出原因：旧结构的做法是先用新版本启动一次守护进程再导出，正忙的就稍后再试，读不了的会附上 SQLite 的报错。完整的清单在 [CLI 参考](CLI-Reference.md#export-dataset)。

## 另见

- [CLI 参考](CLI-Reference.md#export-dataset)
- [变量目录](Variable-Catalog.md)
- [数据、档案与可追溯性](Data-Archive-and-Traceability.md)
- [科研方法](Research-Methodology.md)
