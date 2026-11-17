'use strict';
// The demo's story, scene by scene. Each scene gets (page, state); state carries the ids.
const d = require('./demo.cjs');

// Scroll the window so a section's top sits just under the sticky top bar.
async function reveal(page, target, settleMs = 1200) {
  await target.evaluate((n) => window.scrollBy({ top: n.getBoundingClientRect().top - 88, behavior: 'smooth' }));
  await d.pause(page, settleMs);
}

// The project page keeps its write forms folded under "Edit…"; open the section's fold on camera.
async function openFold(page, block, label) {
  const fold = block.locator('details.edit-fold').first();
  if (!(await fold.count()) || (await fold.evaluate((n) => n.open))) return;
  await d.click(page, fold.locator('summary'), `${label}: Edit…`, 900);
}

async function intro(page) {
  await page.mouse.move(720, 420);
  await d.chapter(page, 'Local demo · simulated grow tent', 'DiAGRI',
    'AI agents for plant-growth research: from a research question to a labelled report, '
    + 'with people in charge of every action on the tent.', null, 5200);
}

async function login(page) {
  await d.sub(page, 'Sign in to the DiAGRI workbench as the on-site operator', 1200);
  await d.typeInto(page, '#login-name', 'dev', 'login name', 110);
  await d.typeInto(page, '#login-secret', d.SECRET, 'login secret', 40);
  await d.click(page, 'button[type="submit"]', 'Sign in', 2600);
}

async function tour(page) {
  await d.sub(page, 'My inbox: everything that waits for a person, most urgent first', 3200);
  await d.click(page, 'a[href="#/environment"]', 'nav Live environment', 1200);
  await d.sub(page, 'Live environment: the simulated tent’s sensors and channels, refreshed every 5 s', 4200);
  await d.click(page, 'a[href="#/safety"]', 'nav Safety limits', 1200);
  await d.sub(page, 'Safety limits are approved by a person and enforced in code. No AI agent can change them.', 1400);
  await d.readThrough(page, 'main', { step: 260, ms: 1400, maxSteps: 4 });
  await d.sub(page, '', 0);
}

async function protocol(page, state) {
  const block = d.section(page, 'Protocols');
  await openFold(page, block, 'Protocols');
  const editor = block.locator('textarea');
  await d.find(page, editor, 'protocol editor');
  const draft = JSON.parse(await editor.inputValue());
  const filled = { ...draft, question: d.QUESTION, hypothesis: d.HYPOTHESIS };
  state.protocolId = filled.id;
  await d.click(page, editor, 'protocol editor', 300);
  await editor.fill(JSON.stringify(filled, null, 2));
  await editor.evaluate((n) => n.scrollTo({ top: 0 }));
  await d.sub(page, 'The research protocol: light 40 % vs 70 %, 4 rounds in 2 blocks, endpoint canopy growth', 3000);
  await editor.evaluate((n) => n.scrollTo({ top: n.scrollHeight * 0.35, behavior: 'smooth' }));
  await d.pause(page, 2600);
  await d.click(page, block.locator('button[type="submit"]'), 'Save protocol', 600);
  await d.waitFor(page, 'protocol saved', async () => ((await d.api(page, `/projects/${state.projectId}`)).protocols || [])
    .some((p) => p.protocol_id === state.protocolId), 15_000);
  await d.pause(page, 1000);
  await d.sub(page, 'Protocols are versioned: a change makes a new version, never an overwrite', 2600);
}

async function round(page, state) {
  const block = d.section(page, 'Rounds');
  await d.choose(page, block.locator('select[name="protocol_id"]'), state.protocolId, 'round protocol');
  await d.click(page, block.locator('button[type="submit"]'), 'Start a round', 600);
  await page.waitForURL(/#\/rounds\//, { timeout: 15_000 }); // the app opens the new round
  const detail = await d.api(page, `/projects/${state.projectId}`);
  if (!detail.rounds || !detail.rounds.length) throw new Error('no round was created');
  state.roundId = detail.rounds[0].round_id;
  await d.pause(page, 1200);
  await d.sub(page, 'Round 1 of 4 is open, in “designing”. The protocol allocates the 70 % light treatment to it.', 3400);
  await d.sub(page, 'It has no stage yet: the run sheet will come from the planner agent', 2600);
}

async function budget(page, state) {
  const block = d.section(page, 'Model call budget');
  await openFold(page, block, 'Model call budget');
  await d.typeInto(page, block.locator('input[name="max_calls"]'), '120', 'max calls', 120);
  await d.typeInto(page, block.locator('input[name="max_cost"]'), '25', 'max cost', 120);
  await d.click(page, block.locator('button[type="submit"]'), 'Set budget', 600);
  await d.handleDialogs(page);
  await d.waitFor(page, 'budget set',
    async () => Boolean((await d.api(page, `/projects/${state.projectId}`)).budget), 15_000);
  await d.sub(page, 'A budget caps how many model calls (and dollars) the agents may spend on this project', 2600);
}

async function project(page, state) {
  await d.chapter(page, 'Chapter 1', 'Set up a research project',
    'A project holds the research protocol, its rounds, a model budget and the conversation with the agents.');
  await d.click(page, 'a[href="#/projects"]', 'nav Projects', 1400);
  const form = d.section(page, 'New project');
  await d.sub(page, 'Create a project for the research question', 400);
  await d.typeInto(page, form.locator('input[name="name"]'), d.PROJECT_NAME, 'project name', 45);
  await d.click(page, form.locator('button[type="submit"]'), 'Create project', 2000);
  const created = (await d.api(page, '/projects')).projects.find((p) => p.name === d.PROJECT_NAME);
  if (!created) throw new Error('the project was not created');
  state.projectId = created.project_id;
  if (!page.url().includes(`#/projects/${state.projectId}`)) {
    await d.click(page, page.locator(`a[href="#/projects/${state.projectId}"]`), 'project link', 2200);
  }
  await d.sub(page, 'The project page: conversation, rounds, protocols and budget', 2400);
  await protocol(page, state);
  await budget(page, state);
  await round(page, state);
}

async function askPlan(page, state) {
  await d.chapter(page, 'Chapter 2', 'Ask the agents',
    'The orchestrator takes the question and delegates; the planner designs a run sheet. Agents propose, people approve.');
  await d.click(page, page.locator(`a[href="#/projects/${state.projectId}"]`), 'breadcrumb project', 2200);
  const chat = d.section(page, 'Conversation');
  await reveal(page, chat);
  const before = await d.sendChat(page, state.projectId, state.roundId, d.ASK_PLAN, 'question');
  await d.sub(page, 'The question goes to the orchestrator agent', 1600);
  if (!d.RECORD) return;
  let mark = await d.lapseStart(page, 'orchestrator reads the project', 4);
  await d.waitFor(page, 'first orchestrator reply', () => d.agentReplied(page, state.projectId, before),
    d.TIMEOUT.reply, () => d.followChat(page));
  await d.lapseEnd(page, mark);
  await d.followChat(page);
  await d.pause(page, 1200);
  await d.sub(page, 'The orchestrator delegates to the planner and says what a one-tent design can and cannot show', 600);
  await d.readLatestReply(page);
  await d.pause(page, 1500);
  await d.sub(page, 'Planner at work: device limits → protocol → draft → validation → saved for review', 0);
  mark = await d.lapseStart(page, 'planner designs and validates the run sheet', 16);
  const ready = d.stable(async () => {
    const r = await d.api(page, `/rounds/${state.roundId}`);
    const stage = (r.stages || []).find((s) => s.state === 'pending_review');
    if (stage) state.stageId = stage.stage_id;
    return Boolean(stage) && (await d.agentsIdle(page, state.projectId));
  });
  await d.waitFor(page, 'run sheet waiting for review', ready, d.TIMEOUT.planner, () => d.followChat(page));
  await d.lapseEnd(page, mark);
  await d.sub(page, '', 0);
  await d.followChat(page);
  await d.pause(page, 1500);
  await d.sub(page, 'The orchestrator reports back: what the run sheet sets up and what to check before approving', 600);
  await d.readLatestReply(page);
  await d.pause(page, 2000);
  await d.sub(page, '', 0);
}

async function review(page, state) {
  await d.chapter(page, 'Chapter 3', 'Review, approve, start',
    'Nothing touches the tent until a person has read the exact run sheet and approved its digest.');
  await d.click(page, 'a[href="#/"]', 'nav My inbox', 1600);
  await d.sub(page, 'The inbox now shows the stage waiting for review', 1800);
  await d.click(page, page.locator(`a[href="#/stages/${state.stageId}"]`), 'stage link', 2400);
  const sheet = d.section(page, 'Run sheet');
  await d.sub(page, 'The run sheet exactly as it would be approved: duration, sampling, timed actions, manual tasks, digest', 400);
  await d.readThrough(page, sheet, { step: 240, ms: 1800, maxSteps: 12 });
  await d.sub(page, 'The automatic checks found hints only, nothing blocking', 2200);
  const controls = d.section(page, 'Controls');
  await reveal(page, controls);
  await d.sub(page, 'Only a person can approve and start a stage. The agents have no such tools.', 1200);
  await d.click(page, controls.locator('button', { hasText: 'Approve run sheet' }), 'Approve run sheet', 600);
  await d.handleDialogs(page);
  await d.pause(page, 1400);
  await d.sub(page, 'Approved: the record binds the operator, the time and the reviewed digest', 2400);
  await d.click(page, controls.locator('button', { hasText: 'Start stage' }), 'Start stage', 600);
  await d.handleDialogs(page);
  await d.waitFor(page, 'stage started',
    async () => (await d.api(page, `/stages/${state.stageId}`)).state !== 'pending_review', 60_000);
  await d.sub(page, 'The stage is running', 1800);
}

async function stage(page, state) {
  await d.chapter(page, 'Chapter 4', 'The stage runs',
    'The executor follows the approved run sheet: deterministic code, no AI model in the loop. '
    + 'Here 21 simulated days are fast-forwarded.');
  await d.click(page, 'a[href="#/environment"]', 'nav Live environment', 1200);
  await d.sub(page, 'Live environment: each channel’s level against what the run sheet wants right now', 1000);
  if (d.RECORD) {
    const mark = await d.lapseStart(page, 'simulated days pass', 6);
    await d.pause(page, 12_000);
    await d.lapseEnd(page, mark);
  } else {
    await d.pause(page, 3000);
  }
  await d.goHash(page, `#/stages/${state.stageId}`, 2200);
  await d.sub(page, 'The stage page: curves, manual tasks and measurements fill in as the days pass', 1200);
  const env = d.section(page, 'Environment');
  const tasks = d.section(page, 'Manual tasks');
  await reveal(page, env);
  if (d.RECORD) {
    const mark = await d.lapseStart(page, '21 simulated days in about 2 minutes', 20);
    let ticks = 0;
    const ended = async () => ['ended', 'stopped'].includes((await d.api(page, `/stages/${state.stageId}`)).state);
    await d.waitFor(page, 'stage ended', ended, d.TIMEOUT.stage, async () => {
      ticks += 1;
      if (ticks % 8 === 0) await reveal(page, (ticks / 8) % 2 ? tasks : env, 0);
    });
    await d.lapseEnd(page, mark);
    await d.click(page, page.locator('button', { hasText: 'Refresh now' }), 'Refresh now', 2500);
  }
  await d.sub(page, 'Stage over: the executor wrote the end actions, read them back and ended the stage', 600);
  await d.readThrough(page, d.section(page, 'History'), { step: 240, ms: 1500, maxSteps: 5 });
  await reveal(page, env, 600);
  await d.sub(page, 'The whole window: temperature, humidity and CO₂ follow the light schedule day by day', 3800);
  await d.sub(page, 'Every planned manual task recorded on time, here by a helper script standing in for the person on site', 600);
  await d.readThrough(page, tasks, { step: 240, ms: 1500, maxSteps: 3 });
  await d.sub(page, 'Daily canopy measurements per plant. Raw records are append-only; a correction points to the original.', 600);
  await d.readThrough(page, d.section(page, 'Measurements'), { step: 260, ms: 1500, maxSteps: 4 });
  await d.sub(page, '', 0);
}

async function analysis(page, state) {
  await d.chapter(page, 'Chapter 5', 'Verify, freeze, analyse',
    'The researcher agent checks the data, freezes an immutable snapshot and analyses it. '
    + 'The server labels the report from the frozen data alone.');
  await d.goHash(page, `#/projects/${state.projectId}`, 2400);
  const chat = d.section(page, 'Conversation');
  await reveal(page, chat);
  const before = await d.sendChat(page, state.projectId, state.roundId, d.ASK_REPORT, 'analysis request');
  if (!d.RECORD) return;
  let mark = await d.lapseStart(page, 'orchestrator checks the round', 4);
  await d.waitFor(page, 'orchestrator reply', () => d.agentReplied(page, state.projectId, before),
    d.TIMEOUT.reply, () => d.followChat(page));
  await d.lapseEnd(page, mark);
  await d.followChat(page);
  await d.pause(page, 1200);
  await d.sub(page, 'The orchestrator checks the round and the stage, then hands the work to the researcher', 600);
  await d.readLatestReply(page);
  await d.sub(page, 'Researcher at work: inspect the data → freeze a snapshot → analyse → publish', 0);
  mark = await d.lapseStart(page, 'researcher verifies, freezes, analyses, publishes', 18);
  const done = d.stable(async () => {
    const r = await d.api(page, `/rounds/${state.roundId}`);
    state.roundState = r.state;
    return r.state === 'delivered' && (await d.agentsIdle(page, state.projectId));
  });
  await d.waitFor(page, 'round delivered', done, d.TIMEOUT.analysis, () => d.followChat(page));
  await d.lapseEnd(page, mark);
  await d.sub(page, '', 0);
  await d.followChat(page);
  await d.pause(page, 1500);
  await d.sub(page, 'The orchestrator’s summary: what the report says and what to do next', 600);
  await d.readLatestReply(page, { maxSteps: 24 });
  await d.pause(page, 1500);
}

async function report(page, state) {
  await d.chapter(page, 'Chapter 6', 'The report',
    'Published, archived with its digest, and labelled by the server: what the data can and cannot support.');
  await d.goHash(page, `#/rounds/${state.roundId}`, 2400);
  if (!d.RECORD) {
    await d.find(page, d.section(page, 'Summary'), 'round summary');
    return;
  }
  const block = d.section(page, 'Report');
  await reveal(page, block);
  await d.sub(page, 'Label and conclusion come from the server’s checks on the frozen data, not from the model', 3200);
  await d.sub(page, 'Why this label, limitations, open questions and a proposal for the next round', 600);
  await d.readThrough(page, block, { step: 220, ms: 2100, maxSteps: 22 });
  await d.sub(page, '', 0);
}

async function outro(page) {
  await d.overlay(page, 'sub', '');
  await d.overlay(page, 'card', 'What you just saw', 'DiAGRI', null, [
    'Agents propose and analyse: orchestrator, planner, researcher',
    'People approve and start: re-authenticated, bound to the reviewed digest',
    'Deterministic execution under hard safety limits, with no AI in the control loop',
    'Every step traceable: append-only raw data, frozen snapshots, labelled reports',
  ]);
  await d.pause(page, 8000);
}

const ORDER = [intro, login, tour, project, askPlan, review, stage, analysis, report, outro];
module.exports = { ORDER };
