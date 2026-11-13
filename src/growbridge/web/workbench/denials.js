// Plain-language messages for every denial code (33 from the wiki, plus two client-side codes).
// Row: [code, zh text, zh advice, en text, en advice]
const ROWS = [
  ["host_unregistered", "这台电脑不是该设备登记的写入主机。", "请在登记的主机上操作，或先把这台电脑登记为写入主机。", "This computer is not the registered write host for the device.", "Work from the registered host, or register this computer as the write host first."],
  ["controls_disabled", "配置里关闭了控制功能。", "请联系管理员在配置中打开控制并重启服务。", "Controls are turned off in the configuration.", "Ask an administrator to turn controls on and restart the service."],
  ["right_invalid", "写入权已失效、被收回，或不适用于这个操作。", "不要重复提交。请通过流程重新获得写入权。", "The write right is invalid, was revoked, or does not fit this action.", "Do not repeat the request. Get a new write right through the workflow."],
  ["right_held", "设备上已有一个阶段持有写入权。", "先暂停、停止或接管那个阶段，再重试。", "A stage already holds the write right for this device.", "Pause, stop or take over that stage first, then try again."],
  ["scope", "这个请求超出了你的权限或写入权的范围。", "检查设备、通道、阶段或实验是否选对；范围不对的请求不能执行。", "The request is outside what your role or write right covers.", "Check that the device, channel, stage or experiment is the right one."],
  ["pump_on_forbidden", "普通写入不能打开水泵。", "请用实验室内网里的浇水功能。", "An ordinary write cannot switch the pump on.", "Use the irrigation action from the lab network."],
  ["interlock", "水泵联锁已启用：还没确认水泵已关。", "请到现场检查水泵并记录现场检查。系统会继续尝试关泵。", "The pump interlock is on: the pump is not confirmed off.", "Check the pump on site and record an on-site check. The system keeps trying to switch it off."],
  ["not_connected", "与设备没有连接，或读不到设备状态。", "等连接恢复后再试一次。", "There is no live connection to the device, or its state could not be read.", "Wait for the connection to come back, then try again."],
  ["stale", "最新数据太旧，不能据此操作。", "等设备传来新数据后再试。", "The latest reading is too old to act on.", "Wait for fresh readings, then try again."],
  ["request_id_reused", "这个请求编号已用于另一个不同的操作。", "新的操作请用新的请求编号；只有重复发送完全相同的请求时才能沿用。", "This request ID was already used for a different action.", "Use a new request ID for a new action. Reuse one only to repeat the identical request."],
  ["not_operator", "只有登录的操作员才能做这个操作。", "请以操作员身份登录后重试。", "Only a signed-in operator can do this.", "Sign in as an operator and try again."],
  ["model_role", "AI 角色不能做这个操作。", "这件事要由操作员来做。", "An AI role is not allowed to do this.", "An operator has to do it."],
  ["reauth_required", "这个操作需要你在最近 5 分钟内重新输入口令。", "输入口令确认后，操作会再试一次。", "This action needs you to enter your secret again within the last 5 minutes.", "Enter your secret to confirm, and the action will be tried once more."],
  ["entry", "请求不是从允许的入口发来的。", "请使用登记过的地址访问；浇水只能在实验室内网里进行。", "The request did not come in through an allowed entry.", "Use a registered address. Irrigation works only from the lab network."],
  ["approval_invalid", "这个阶段没有有效的批准，或批准后内容已变化。", "处理运行单上的问题后，重新批准这个阶段。", "The stage has no valid approval, or it changed after it was approved.", "Resolve the findings on the run sheet and approve the stage again."],
  ["state", "对象不存在、当前状态不允许这个操作，或请求执行时它已经变了。", "刷新页面看最新状态，再决定是否重试。", "The item does not exist, is not in a state that allows this, or changed while the request ran.", "Refresh the page to see the current state, then decide whether to try again."],
  ["safety_conflict", "安全配置里的保护规则作用在运行单没有交给主机控制的通道上。", "修改运行单（生成新版本）或安全配置，然后重新批准。", "A protection rule in the safety configuration acts on a channel the run sheet does not hand to the host.", "Change the run sheet (a new version) or the safety configuration, then approve again."],
  ["budget", "项目的调用或费用预算已用完，或还没设置。", "先停下。请由操作员设置或提高项目预算，或亲自决定这个任务。", "The project's call or cost budget is used up, or was never set.", "Stop. An operator should set or raise the budget, or decide the task personally."],
  ["session", "没有登录，或登录已失效。", "请重新登录。", "You are not signed in, or the session has ended.", "Sign in again."],
  ["member", "提交人没有对应的 CSC 项目成员身份。", "只有启用了计算服务才会出现；请联系管理员核对成员映射。", "The submitter is not mapped to a CSC project member.", "Only seen when the compute service is on. Ask an administrator to check the member mapping."],
  ["quota", "计算额度不够，或已达到重试上限。", "请联系管理员核对任务预算和项目余额。", "There is not enough compute budget, or the retry limit is reached.", "Ask an administrator to check the task budget and project balance."],
  ["param", "参数不对：模板、取值或输入文件不符合要求。", "按提示检查并改正各项参数后再提交。", "A parameter is not valid: the template, a value or an input file does not fit.", "Check and correct the parameters, then submit again."],
  ["clock_unsynced", "设备时钟还没校准，现在不能冻结数据。", "等时钟校准后再冻结。", "The clock is not synchronised, so data cannot be frozen now.", "Freeze again once the clock is synchronised."],
  ["script_hash", "分析脚本和协议里登记的（或已冻结的）脚本不一致。", "请使用已冻结的脚本。", "The analysis script differs from the one in the protocol or the one already frozen.", "Use the frozen script."],
  ["snapshot_incomplete", "数据快照不完整，或文件和清单对不上。", "重新冻结一份快照，用新的那份。", "The data snapshot is incomplete, or its files do not match its manifest.", "Freeze a new snapshot and use that one."],
  ["already_run", "验证性分析在这份快照上已经跑过，或正在运行。", "不要再跑；验证性分析只能跑一次。", "The confirmatory analysis already ran on this snapshot, or is running.", "Do not run it again. A confirmatory analysis runs only once."],
  ["batches", "留出集登记不合格：开发批次不到 2 个、没有留出批次、批次重叠，或批次名为空或重复。", "至少登记 2 个开发批次和 1 个留出批次，且互不重叠。", "The holdout is not valid: fewer than 2 development batches, no holdout batch, overlapping batches, or empty or repeated names.", "Register at least 2 development batches and 1 holdout batch, with no overlap."],
  ["model_unregistered", "评估前这个模型没有登记到留出集。", "先登记模型、特征和预处理，再评估。", "The model was not registered for the holdout before evaluation.", "Register the model, its features and its preprocessing first."],
  ["sandbox_unavailable", "这个平台没有隔离环境，不能运行分析脚本。", "请在有隔离环境的平台上运行分析。", "This platform has no isolation backend, so analysis scripts cannot run.", "Run the analysis on a platform that has the sandbox."],
  ["unsettled", "控制服务还没启动完，或之前有一次操作的结果还不确定。", "先等启动完成；否则要先读回设备状态或做现场检查，确认结果后才能继续写入。", "The control service is still starting, or an earlier action has an unknown result.", "Wait for startup. Otherwise settle the result by reading back or an on-site check before writing again."],
  ["cooldown", "正在浇水，或距上一次浇水还不够久。", "等一会儿再浇。", "Irrigation is running, or the last one started too recently.", "Wait a while, then irrigate again."],
  ["unavailable", "这个功能的后端没有配置（搜索、计算服务、隔离环境或留出集登记）。", "你无法解决；这个服务在部署时没有包含它。", "An optional backend is not configured (search, compute service, sandbox or holdout registry).", "Nothing you can do; this installation was set up without it."],
  ["locked", "登录失败次数太多，暂时被锁定。", "等 15 分钟后再试。", "Too many failed sign-ins, so sign-in is locked for now.", "Wait 15 minutes, then try again."],
  ["validation", "有些输入不符合要求。", "按字段旁的提示改正后再提交。", "Some of the input is not valid.", "Fix the fields marked below and submit again."],
  ["network", "连不上服务器。", "检查网络连接，稍后再试。", "Could not reach the server.", "Check the network connection and try again in a moment."],
];

export const DENIALS = Object.fromEntries(
  ROWS.map(([code, zhText, zhAdvice, enText, enAdvice]) => [
    code,
    { zh: { text: zhText, advice: zhAdvice }, en: { text: enText, advice: enAdvice } },
  ]),
);

export function describeDenial(code, lang) {
  const entry = Object.hasOwn(DENIALS, code) ? DENIALS[code] : null;
  if (!entry) return null;
  return entry[lang] || entry.en;
}
