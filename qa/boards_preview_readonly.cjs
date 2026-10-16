/** 仅验收内存演示看板；真实 Session，headless，所有业务写请求均阻断。 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const os = require('node:os');
const { chromium } = require('../src/frontend/node_modules/playwright-core');

const root = path.resolve(__dirname, '..');
const evidence = path.join(root, 'output/playwright/boards_refinement_20261016');
const browserTemp = path.join(root, '.tmp/boards_20261016/browser');
const statePath = process.env.BOARDS_QA_STORAGE_STATE;
const base = new URL(process.env.BOARDS_QA_BASE_URL || 'http://localhost:8080');
const routes = [
  ['production-line', '产线大屏', 3], ['warehouse', '仓库大屏', 3],
  ['production-progress', '生产进度看板', 0], ['production', '生产大屏', 3],
];
const report = {
  qa_result_version: 1, status: 'RUNNING', not_covered: [], mode: 'authenticated-memory-demo-read-only',
  checks: [], screenshots: [], measurements: [], blockedWrites: [], pageErrors: [],
  cleanup: { browserTemp, created: false, closed: false, removed: false, verifiedAbsent: false },
};
let browser;
let ownsTemp = false;
const previousTemp = { TEMP: process.env.TEMP, TMP: process.env.TMP, TMPDIR: process.env.TMPDIR };
function check(condition, name) { assert.ok(condition, name); report.checks.push(name); }
function prerequisite(condition, name) {
  if (!condition) throw Object.assign(new Error(name), { blocked: true });
  report.checks.push(name);
}
async function protectWrites(context) {
  await context.route('**/*', async route => {
    const request = route.request();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      report.blockedWrites.push({ method: request.method(), path: new URL(request.url()).pathname });
      await route.abort('blockedbyclient');
    } else await route.continue();
  });
}
function save() { fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); }
async function capture(page, name) {
  const filename = `${name}.png`;
  await page.screenshot({ path: path.join(evidence, filename), animations: 'disabled' });
  report.screenshots.push(filename);
}

async function captureMotion(page, name) {
  const filename = `${name}.png`;
  await page.screenshot({ path: path.join(evidence, filename), animations: 'allow' });
  report.screenshots.push(filename);
}

// 取真实时间与 native scrollTop；跨周期时加回原内容高度，不把跳回零误判为倒退。
async function sampleScrolls(page, duration = 1100, interval = 100) {
  return page.evaluate(async ({ duration, interval }) => {
    const elements = [...document.querySelectorAll('.board-table-scroll:not([data-motion="feed"])')];
    const states = elements.map(element => {
      const original = element.querySelector('[data-loop-content]');
      const header = element.querySelector('thead');
      return { element, period: original?.getBoundingClientRect().height || 0,
        overflow: (original?.getBoundingClientRect().height || 0) + (header?.getBoundingClientRect().height || 0) > element.clientHeight + 1,
        panel: element.closest('.board-panel')?.getAttribute('aria-label'), samples: [] };
    });
    const start = performance.now();
    do {
      const time = performance.now();
      states.forEach(state => state.samples.push({ time, top: state.element.scrollTop }));
      if (time - start >= duration) break;
      await new Promise(resolve => setTimeout(resolve, interval));
    } while (true);
    return states.map(({ element, period, overflow, panel, samples }) => {
      let distance = 0;
      let wraps = 0;
      for (let index = 1; index < samples.length; index++) {
        let difference = samples[index].top - samples[index - 1].top;
        if (difference < -period / 2) { difference += period; wraps++; }
        distance += difference;
      }
      const elapsed = samples.at(-1).time - samples[0].time;
      return { panel, period, overflow, active: element.getAttribute('data-loop-active'),
        copyCount: element.querySelectorAll('[data-loop-copy]').length, samples,
        distance, elapsed, wraps, speed: elapsed > 0 ? distance * 1000 / elapsed : 0 };
    });
  }, { duration, interval });
}

async function sampleOneScroll(locator, duration = 550) {
  return locator.evaluate(async (element, duration) => {
    const period = element.querySelector('[data-loop-content]')?.getBoundingClientRect().height || 0;
    const samples = [];
    const start = performance.now();
    do {
      samples.push({ time: performance.now(), top: element.scrollTop });
      if (performance.now() - start >= duration) break;
      await new Promise(resolve => setTimeout(resolve, 75));
    } while (true);
    let distance = 0;
    for (let index = 1; index < samples.length; index++) {
      let delta = samples[index].top - samples[index - 1].top;
      if (delta < -period / 2) delta += period;
      distance += delta;
    }
    return { distance, speed: distance * 1000 / (samples.at(-1).time - samples[0].time),
      range: Math.max(...samples.map(sample => sample.top)) - Math.min(...samples.map(sample => sample.top)) };
  }, duration);
}

async function decorations(page, slug, reduced = false) {
  const measured = await page.evaluate(async ({ reduced }) => {
    const header = [...document.querySelectorAll('path.board-header-sweep')];
    const slashes = [...document.querySelectorAll('span.board-metric-slash')];
    const targets = [...header, ...slashes];
    const samples = targets.map(() => []);
    const start = performance.now();
    do {
      targets.forEach((element, index) => samples[index].push(Number(getComputedStyle(element).opacity)));
      if (performance.now() - start >= (reduced ? 500 : 2700)) break;
      await new Promise(resolve => setTimeout(resolve, 170));
    } while (true);
    return { headerCount: header.length, slashCount: slashes.length, reduced,
      header: samples.slice(0, header.length).map(values => ({ min: Math.min(...values), max: Math.max(...values) })),
      slashes: samples.slice(header.length).map(values => ({ min: Math.min(...values), max: Math.max(...values) })) };
  }, { reduced });
  report.measurements.push({ slug, decorationMotion: measured });
  check(measured.headerCount === 8, `${slug}:头部八个动效箭头存在`);
  const changing = value => value.max - value.min > .05;
  const stable = value => value.max - value.min < .001;
  check(measured.header.every(reduced ? stable : changing), `${slug}:头部透明度实测${reduced ? '缩减时静止' : '持续变化'}`);
  if (slug !== 'production-progress') {
    check(measured.slashCount > 0 && measured.slashes.every(reduced ? stable : changing), `${slug}:指标斜线透明度实测${reduced ? '缩减时静止' : '错峰变化'}`);
  }
}

async function boundaryMotion(page, slug) {
  const boundaries = await page.evaluate(async () => {
    const entries = [...document.querySelectorAll('.board-table-scroll[data-loop-active="true"]')].map(element => {
      const original = element.querySelector('[data-loop-content]');
      const copy = element.querySelector('[data-loop-copy]');
      const period = original.getBoundingClientRect().height;
      element.scrollTop = period - 8;
      return { element, original, copy, period, before: element.scrollTop, samples: [] };
    });
    const start = performance.now();
    do {
      entries.forEach(entry => {
        const { element, original, copy } = entry;
        const bounds = element.getBoundingClientRect();
        const sourceBounds = original.getBoundingClientRect();
        const copyBounds = copy.getBoundingClientRect();
        const headerHeight = element.querySelector('thead')?.getBoundingClientRect().height || 0;
        const ys = [bounds.top + headerHeight + 3, (bounds.top + headerHeight + bounds.bottom) / 2, bounds.bottom - 4];
        // inert 副本不参与命中测试，按实际绘制边界验证三处均被内容覆盖。
        const covered = ys.every(y => [sourceBounds, copyBounds].some(rect => y >= rect.top - 1 && y <= rect.bottom + 1));
        entry.samples.push({ top: element.scrollTop, covered,
          seam: Math.abs(copyBounds.top - sourceBounds.bottom),
          bottomCovered: copyBounds.bottom >= bounds.bottom - 2 });
      });
      if (performance.now() - start >= 550) break;
      await new Promise(resolve => setTimeout(resolve, 40));
    } while (true);
    return entries.map(({ element, original, copy, period, before, samples }) => ({
      panel: element.closest('.board-panel')?.getAttribute('aria-label'), period, before, samples,
      sameContent: original.textContent.replace(/\s+/g, ' ').trim() === copy.textContent.replace(/\s+/g, ' ').trim(),
      sameItemCount: original.children.length === copy.children.length,
      copyHidden: copy.getAttribute('aria-hidden') === 'true', copyInert: copy.inert === true,
      wrapped: samples.some(sample => sample.top < before - period / 2),
    }));
  });
  report.measurements.push({ slug, boundaries });
  for (const boundary of boundaries) {
    const name = `${slug}/${boundary.panel}`;
    check(boundary.sameContent && boundary.sameItemCount && boundary.copyHidden && boundary.copyInert, `${name}:副本完整且辅助技术不可访问`);
    check(boundary.wrapped, `${name}:临界位置真实跨周期`);
    check(boundary.samples.every(sample => sample.covered && sample.bottomCovered && sample.seam <= 2), `${name}:首尾紧接且跨界无空白`);
  }
  await captureMotion(page, `${slug}-motion-boundary`);
}

async function pauseMotion(page, slug, panels) {
  for (const panel of panels) {
    const scroll = page.locator(`.board-panel[aria-label="${panel}"] .board-table-scroll`).first();
    const result = { slug, panel, pauseMotion: {} };
    report.measurements.push(result);
    await scroll.hover();
    await page.waitForTimeout(100);
    const hovered = await sampleOneScroll(scroll, 400);
    result.pauseMotion.hovered = hovered;
    check(hovered.range <= 1, `${slug}/${panel}:悬停实际暂停`);
    await page.mouse.move(10, 10);
    const resumed = await sampleOneScroll(scroll);
    result.pauseMotion.resumed = resumed;
    check(resumed.speed >= 32 && resumed.speed <= 48, `${slug}/${panel}:移出后连续恢复`);
    await scroll.evaluate(element => element.focus({ preventScroll: true }));
    await page.mouse.move(10, 10);
    await page.waitForTimeout(100);
    const focused = await sampleOneScroll(scroll, 400);
    result.pauseMotion.focused = focused;
    check(focused.range <= 1, `${slug}/${panel}:持焦移出仍暂停`);
    await scroll.evaluate(element => { if (element.contains(document.activeElement)) document.activeElement.blur(); });
    const blurred = await sampleOneScroll(scroll);
    result.pauseMotion.blurred = blurred;
    check(blurred.speed >= 32 && blurred.speed <= 48, `${slug}/${panel}:失焦后连续恢复`);
  }
  // DOM 可见性事件模拟只改变浏览器文档状态，不写任何业务数据。
  await page.evaluate(() => {
    window.__boardsQaVisibility = Object.getOwnPropertyDescriptor(document, 'hidden');
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  try {
    const hidden = await sampleScrolls(page, 450);
    check(hidden.every(value => Math.abs(value.distance) <= 1), `${slug}:document.hidden事件模拟暂停`);
  } finally {
    await page.evaluate(() => {
      if (window.__boardsQaVisibility) Object.defineProperty(document, 'hidden', window.__boardsQaVisibility);
      else delete document.hidden;
      delete window.__boardsQaVisibility;
      document.dispatchEvent(new Event('visibilitychange'));
    });
  }
}

async function reducedMotion(page, slug) {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.waitForTimeout(120);
  check(await page.locator('[data-loop-copy]').count() === 0, `${slug}:缩减动画移除所有循环副本`);
  const still = await sampleScrolls(page, 450);
  check(still.every(value => Math.abs(value.distance) <= 1), `${slug}:缩减动画原内容自动滚动停止`);
  await decorations(page, slug, true);
  const lastItems = await page.locator('.board-table-scroll:not([data-motion="feed"])').evaluateAll(elements => elements.map(element => {
    const original = element.querySelector('[data-loop-content]');
    element.scrollTop = element.scrollHeight;
    const items = original ? [...original.querySelectorAll('tr, article, li')] : [];
    const last = items.at(-1) || original?.lastElementChild;
    const bounds = element.getBoundingClientRect();
    const itemBounds = last?.getBoundingClientRect();
    return { panel: element.closest('.board-panel')?.getAttribute('aria-label'), original: Boolean(original),
      top: element.scrollTop, visible: Boolean(itemBounds && itemBounds.bottom <= bounds.bottom + 1 && itemBounds.bottom > bounds.top) };
  }));
  report.measurements.push({ slug, reducedLastItems: lastItems });
  check(lastItems.every(item => item.original && item.visible), `${slug}:缩减动画保留原内容且末项手动可见`);
  await capture(page, `${slug}-reduced-last-items`);
}

async function feedMotion(page) {
  const feed = page.locator('.board-table-scroll[data-motion="feed"]');
  check(await feed.count() === 1, '生产大屏:实时报工独立feed模式');
  const sample = duration => feed.evaluate(async (element, duration) => {
    const values = [];
    const start = performance.now();
    do {
      const row = element.querySelector('[data-feed-row]');
      const text = row?.textContent || '';
      let hash = 5381;
      for (const char of text) hash = ((hash * 33) ^ char.charCodeAt(0)) >>> 0;
      values.push({ time: performance.now() - start, hash, height: row?.getBoundingClientRect().height || 0,
        opacity: row ? Number(getComputedStyle(row).opacity) : 0 });
      if (performance.now() - start >= duration) break;
      await new Promise(resolve => setTimeout(resolve, 120));
    } while (true);
    return values;
  }, duration);
  await feed.hover();
  const moving = await sample(1380);
  const measured = { moving };
  report.measurements.push({ slug: 'production', feedMotion: measured });
  check(moving[0].hash !== moving.at(-1).hash, '实时报工:约1.3秒后首条真实换行且悬停继续');
  const transitions = moving.some((value, index) => index > 0 && value.hash === moving[index - 1].hash
    && Math.abs(value.height - moving[index - 1].height) > 1 && Math.abs(value.opacity - moving[index - 1].opacity) > .02);
  check(transitions, '实时报工:120ms连续采样确认行高与透明度真实渐变');
  check(Math.min(...moving.map(value => value.height)) < 30 && Math.max(...moving.map(value => value.height)) > 30
    && Math.min(...moving.map(value => value.opacity)) < .9, '实时报工:顶行实际收缩淡出');
  await captureMotion(page, 'production-feed-motion');
  await feed.evaluate(element => element.focus({ preventScroll: true }));
  await page.mouse.move(10, 10);
  const focused = await sample(1260);
  measured.focused = focused;
  check(new Set(focused.map(value => value.hash)).size === 1
    && Math.max(...focused.map(value => value.height)) - Math.min(...focused.map(value => value.height)) <= 1
    && Math.max(...focused.map(value => value.opacity)) - Math.min(...focused.map(value => value.opacity)) < .01, '实时报工:持焦移出仍暂停换行与渐变');
  await feed.evaluate(element => element.blur());
  const resumed = await sample(1380);
  measured.resumed = resumed;
  check(new Set(resumed.map(value => value.hash)).size > 1, '实时报工:失焦恢复逐条换行');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const reduced = await sample(1260);
  measured.reduced = reduced;
  check(new Set(reduced.map(value => value.hash)).size === 1 && reduced.every(value => Math.abs(value.height - 38) <= 1 && value.opacity === 1), '实时报工:缩减动画停止换行并恢复完整38px行');
}

async function motionPages(page) {
  const required = {
    'production-line': ['质检信息', '工单执行进度', '人员生产统计', '任务执行进度'],
    warehouse: ['入库商品排行', '实时库存统计', '出入库流水'],
    'production-progress': ['工单执行进度'], production: ['工单执行进度', '任务执行进度'],
  };
  for (const [slug] of routes) {
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.goto(new URL(`/boards/${slug}`, base).href, { waitUntil: 'networkidle' });
    await page.locator('.board-page').waitFor();
    await page.mouse.move(10, 10);
    for (const name of required[slug]) {
      check(await page.locator(`.board-panel[aria-label="${name}"] .board-table-scroll:not([data-motion="feed"])`).count() === 1, `${slug}/${name}:连续滚动区域存在`);
    }
    await decorations(page, slug);
    const samples = await sampleScrolls(page);
    report.measurements.push({ slug, scrollMotion: samples });
    for (const measured of samples) {
      const name = `${slug}/${measured.panel}`;
      if (measured.overflow) {
        check(measured.active === 'true' && measured.copyCount === 1, `${name}:实际溢出才开启循环副本`);
        check(measured.speed >= 35 && measured.speed <= 45, `${name}:真实速度40±5设计CSSpx每秒`);
      } else {
        check(measured.copyCount === 0 && Math.abs(measured.distance) <= 1, `${name}:内容能容纳时静止且无副本`);
      }
    }
    await boundaryMotion(page, slug);
    await pauseMotion(page, slug, samples.filter(item => item.overflow).map(item => item.panel));
    if (slug === 'production') await feedMotion(page);
    await reducedMotion(page, slug);
  }
}

// 仅读取本地内存演示图表的运行中 UI；不访问参照站点或读取其业务数据。
async function chartUi(page) {
  return page.locator('.board-chart').evaluateAll(elements => elements.map((element, index) => {
    const chart = element.__vueParentComponent?.exposed?.getChart?.();
    if (!chart) return { index, available: false, label: element.getAttribute('aria-label') };
    const option = chart.getOption();
    const rect = element.getBoundingClientRect();
    const legends = (option.legend || []).map((legend, legendIndex) => {
      const model = chart.getModel().getComponent('legend', legendIndex);
      const view = chart.getViewOfComponentModel(model);
      const info = view?._getPageInfo?.(model);
      const point = name => {
        const icon = view?._controllerGroup?.childOfName(name);
        if (!icon) return undefined;
        const bounds = icon.getBoundingRect();
        const transform = icon.getComputedTransform() || [1, 0, 0, 1, 0, 0];
        const x = bounds.x + bounds.width / 2;
        const y = bounds.y + bounds.height / 2;
        return { x: rect.left + (transform[0] * x + transform[2] * y + transform[4]) * rect.width / chart.getWidth(),
          y: rect.top + (transform[1] * x + transform[3] * y + transform[5]) * rect.height / chart.getHeight() };
      };
      return { index: legendIndex, type: legend.type, scrollDataIndex: model.get('scrollDataIndex'),
        pageIndex: info?.pageIndex, pageCount: info?.pageCount,
        hasNext: info?.pageNextDataIndex != null, hasPrevious: info?.pagePrevDataIndex != null,
        pageText: view?._controllerGroup?.childOfName('pageText')?.style?.text,
        next: point('pageNext'), previous: point('pagePrev') };
    });
    const renderedText = chart.getZr().storage.getDisplayList().map(item => item.style?.text).filter(value => typeof value === 'string');
    return { index, available: true, label: element.getAttribute('aria-label'), legends,
      axes: (option.xAxis || []).filter(axis => axis.type === 'category').map(axis => axis.data),
      renderedMonthLabels: renderedText.filter(value => /^10[-/]\d{1,2}$/.test(value)) };
  }));
}

async function validateChartUi(page, slug, viewport) {
  const initial = await chartUi(page);
  report.measurements.push({ slug, viewport, chartUi: initial });
  if (initial.some(chart => !chart.available)) {
    const limitation = `${slug}/${viewport}:BoardChart未提供本地实例，月度轴和canvas图例分页尚未验证`;
    if (!report.not_covered.includes(limitation)) report.not_covered.push(limitation);
    return;
  }
  for (const chart of initial) {
    for (const axis of chart.axes) {
      check(axis.length === 31 && axis[0] === '10-01' && axis.at(-1) === '10-31', `${slug}/${viewport}/${chart.index}:运行中图表覆盖完整31日月轴`);
      check(chart.renderedMonthLabels.length >= 2, `${slug}/${viewport}/${chart.index}:canvas实际绘出月度日期标签`);
    }
    for (const legend of chart.legends.filter(item => item.type === 'scroll')) {
      check(legend.pageCount > 1 && legend.pageIndex === 0 && legend.hasNext && !legend.hasPrevious, `${slug}/${viewport}/${chart.index}:图例分页真实渲染并从首页开始`);
      let current = legend;
      const visited = [{ index: current.pageIndex, text: current.pageText }];
      for (let step = 0; current.hasNext && step < legend.pageCount; step++) {
        check(Boolean(current.next), `${slug}/${viewport}/${chart.index}:下一页图形可定位`);
        await page.mouse.click(current.next.x, current.next.y);
        await page.waitForTimeout(120);
        const next = (await chartUi(page))[chart.index].legends[legend.index];
        check(next.pageIndex > current.pageIndex && next.scrollDataIndex !== current.scrollDataIndex, `${slug}/${viewport}/${chart.index}:点击图例下一页后内容与页码同步`);
        current = next;
        visited.push({ index: current.pageIndex, text: current.pageText });
      }
      check(current.pageIndex === legend.pageCount - 1 && !current.hasNext && current.hasPrevious, `${slug}/${viewport}/${chart.index}:图例可到末页且下一页禁用`);
      await capture(page, `${slug}-chart-${chart.index}-legend-last-${viewport.join('x')}`);
      for (let step = 0; current.hasPrevious && step < legend.pageCount; step++) {
        check(Boolean(current.previous), `${slug}/${viewport}/${chart.index}:上一页图形可定位`);
        await page.mouse.click(current.previous.x, current.previous.y);
        await page.waitForTimeout(120);
        const previous = (await chartUi(page))[chart.index].legends[legend.index];
        check(previous.pageIndex < current.pageIndex, `${slug}/${viewport}/${chart.index}:点击图例上一页恢复前页`);
        current = previous;
      }
      check(current.pageIndex === 0 && !current.hasPrevious, `${slug}/${viewport}/${chart.index}:图例可返回首页且上一页禁用`);
      report.measurements.push({ slug, viewport, chart: chart.index, legend: legend.index, legendPagesVisited: visited });
    }
  }
}

async function validatePage(page, slug, title, charts, viewport) {
  await page.setViewportSize({ width: viewport[0], height: viewport[1] });
  await page.goto(new URL(`/boards/${slug}`, base).href, { waitUntil: 'networkidle' });
  await page.locator('.board-page').waitFor();
  await page.getByRole('heading', { name: slug === 'production' ? '生产中控大屏' : title, exact: true }).waitFor();
  check(await page.locator('.app-sidebar, .app-header, .erp-layout').count() === 0, `${slug}/${viewport}:独立布局`);
  check(await page.locator('.board-demo-badge').textContent() === '演示数据 · 不写入数据库', `${slug}/${viewport}:演示标记`);
  check(await page.locator('.board-chart canvas').count() === charts, `${slug}/${viewport}:图表渲染数`);
  const measurement = await page.evaluate(async () => {
    await document.fonts.ready;
    const shell = document.querySelector('.board-page');
    const canvas = document.querySelector('.board-canvas');
    const panels = [...document.querySelectorAll('.board-panel')];
    const clockStyle = getComputedStyle(document.querySelector('.board-clock'));
    const clockFamily = clockStyle.fontFamily.split(',')[0].trim().replace(/^['"]|['"]$/g, '');
    const faces = [...document.fonts].map(face => ({ family: face.family.replace(/^['"]|['"]$/g, ''), status: face.status }));
    const grid = document.querySelector('.board-grid');
    const rect = canvas.getBoundingClientRect();
    const outside = [...document.querySelectorAll('.board-search, .board-panel, .board-metric')].filter(e => {
      const r = e.getBoundingClientRect();
      return r.left < -.5 || r.right > innerWidth + .5 || r.top < -.5 || r.bottom > innerHeight + .5;
    }).map(e => e.className);
    return {
      viewport: [innerWidth, innerHeight], background: getComputedStyle(shell).backgroundColor,
      canvas: [rect.x, rect.y, rect.width, rect.height], outside,
      documentOverflow: [document.documentElement.scrollWidth > innerWidth, document.documentElement.scrollHeight > innerHeight],
      title: { size: getComputedStyle(document.querySelector('h1')).fontSize, weight: getComputedStyle(document.querySelector('h1')).fontWeight },
      typography: { pageFamily: getComputedStyle(shell).fontFamily, clockFamily,
        clockLoaded: document.fonts.check(`${clockStyle.fontSize} "${clockFamily}"`),
        declaredClockFaces: faces.filter(face => face.family === clockFamily),
        numericFaces: faces.filter(face => face.family === 'dpNum') },
      gridColumns: grid ? getComputedStyle(grid).gridTemplateColumns.split(' ').map(Number.parseFloat) : [],
      metrics: [...document.querySelectorAll('.board-metric')].map(element => {
        const style = getComputedStyle(element);
        const value = element.querySelector('.board-metric-value');
        const numeric = value?.cloneNode(true);
        numeric?.querySelectorAll('.board-metric-unit').forEach(unit => unit.remove());
        const valueStyle = value ? getComputedStyle(value) : undefined;
        const unit = element.querySelector('.board-metric-unit');
        const comparison = element.querySelector('.board-comparison');
        const frame = element.querySelector('.board-metric-frame');
        return { label: element.querySelector('.board-metric-label')?.textContent,
          width: Number.parseFloat(style.width), height: Number.parseFloat(style.height),
          frameLoaded: Boolean(frame?.complete && frame.naturalWidth > 0),
          decorationLayers: [getComputedStyle(element, '::before').content, getComputedStyle(element, '::after').content],
          value: { text: numeric?.textContent, font: valueStyle?.fontFamily, size: valueStyle?.fontSize,
            weight: valueStyle?.fontWeight, compact: value?.classList.contains('is-compact') },
          unit: unit ? { text: unit.textContent, size: getComputedStyle(unit).fontSize } : undefined,
          comparison: comparison ? { label: comparison.querySelector('.board-comparison-label')?.textContent,
            value: comparison.querySelector('.board-comparison-value')?.textContent } : undefined };
      }),
      panels: panels.map(e => { const s = getComputedStyle(e); return { name: e.getAttribute('aria-label'),
        borders: [s.borderTopWidth, s.borderRightWidth, s.borderBottomWidth, s.borderLeftWidth], color: s.borderTopColor,
        background: s.backgroundColor, radius: s.borderRadius }; }),
      tables: [...document.querySelectorAll('table')].map(table => {
        const row = table.querySelector('tbody tr');
        const cells = row ? [...row.children] : [];
        return { process: table.classList.contains('board-processes'), imageRows: Boolean(table.closest('.has-product-image')),
          header: table.querySelector('th') ? getComputedStyle(table.querySelector('th')).backgroundColor : '',
          headerHeight: table.querySelector('th') ? Number.parseFloat(getComputedStyle(table.querySelector('th')).height) : 0,
          rowHeight: row ? row.offsetHeight : 0, firstBorder: cells[0] ? getComputedStyle(cells[0]).borderLeftWidth : '',
          lastBorder: cells.at(-1) ? getComputedStyle(cells.at(-1)).borderRightWidth : '',
          lastRowBottom: table.querySelector('tbody tr:last-child td') ? getComputedStyle(table.querySelector('tbody tr:last-child td')).borderBottomWidth : '' };
      }),
      processNodes: [...document.querySelectorAll('[data-loop-content] .board-process-node')].map(element => {
        const style = getComputedStyle(element);
        return [Number.parseFloat(style.width), Number.parseFloat(style.height)];
      }),
      processNodeText: [...document.querySelectorAll('[data-loop-content] .board-process-node')].map(element => {
        const range = document.createRange();
        range.selectNodeContents(element);
        const scale = element.getBoundingClientRect().width / Number.parseFloat(getComputedStyle(element).width);
        return { text: element.textContent, width: range.getBoundingClientRect().width / scale, available: element.clientWidth };
      }),
      persistedDemo: Object.values(localStorage).some(value => value.includes('DEMO-MO-') || value.includes('DEMO-P-')),
      scrollbars: [...document.querySelectorAll('.board-table-scroll, .board-process-cell')].map(element => {
        const style = getComputedStyle(element);
        const scrollbar = getComputedStyle(element, '::-webkit-scrollbar');
        return { width: style.scrollbarWidth, display: scrollbar.display, pseudoWidth: scrollbar.width,
          pseudoHeight: scrollbar.height, overflowX: style.overflowX, overflowY: style.overflowY };
      }),
    };
  });
  report.measurements.push({ slug, ...measurement });
  check(measurement.background === 'rgb(8, 17, 26)', `${slug}/${viewport}:页面背景`);
  check(measurement.title.size === '44px' && measurement.title.weight === '700', `${slug}/${viewport}:标题尺寸`);
  check(measurement.typography.pageFamily === 'sans-serif', `${slug}/${viewport}:正文使用确认的sans-serif字体`);
  check(measurement.typography.clockFamily === 'time' && measurement.typography.clockLoaded && measurement.typography.declaredClockFaces.length > 0
    && measurement.typography.declaredClockFaces.every(face => face.status === 'loaded'), `${slug}/${viewport}:本地时钟font-face实际加载`);
  if (slug !== 'production-progress') {
    check(measurement.gridColumns.length === 3 && measurement.gridColumns.every((value, index) => Math.abs(value - [566, 758, 566][index]) <= .1), `${slug}/${viewport}:三列宽度566/758/566`);
    check(measurement.metrics.length === 9 && measurement.metrics.every(metric => Math.abs(metric.width - 236) <= 1
      && Math.abs(metric.height - 97.25) <= 1), `${slug}/${viewport}:九卡片设计尺寸236×97.25`);
    check(measurement.metrics.every(metric => metric.frameLoaded && metric.decorationLayers.every(content => ['none', 'normal', ''].includes(content))), `${slug}/${viewport}:卡片装饰资产实际加载且无重复伪元素`);
    check(measurement.metrics.filter(metric => metric.comparison).length === (slug === 'warehouse' ? 0 : 3), `${slug}/${viewport}:比较区数量与对应原站页面一致`);
    check(measurement.metrics.filter(metric => metric.comparison).every(metric => metric.comparison.label?.trim()
      && metric.comparison.value?.trim()), `${slug}/${viewport}:三项比较区均有标题和独立数值`);
    check(measurement.typography.numericFaces.length > 0 && measurement.typography.numericFaces.every(face => face.status === 'loaded'), `${slug}/${viewport}:dpNum数字字体实际加载`);
    check(measurement.metrics.every(metric => metric.value.font?.includes('dpNum') && metric.value.weight === '400'
      && metric.value.size === (metric.value.compact ? '32px' : '48px')), `${slug}/${viewport}:指标数字字体字重与长数紧凑尺寸`);
    check(measurement.metrics.filter(metric => metric.unit).every(metric => metric.unit.text?.trim() === '%'
      && metric.unit.size === '24px' && !metric.value.text?.includes('%')), `${slug}/${viewport}:百分比单位独立为24px`);
  }
  check(measurement.outside.length === 0 && !measurement.documentOverflow.some(Boolean), `${slug}/${viewport}:无页面溢出`);
  check(!measurement.persistedDemo, `${slug}/${viewport}:无模拟数据持久化`);
  check(measurement.scrollbars.every(s => s.width === 'none' && s.display === 'none' && s.pseudoWidth === '0px' && s.pseudoHeight === '0px'), `${slug}/${viewport}:纵向列表与横向工序滚动条均隐藏`);
  check(measurement.panels.every(p => p.borders.every(v => v === '1px') && p.color === 'rgb(41, 74, 96)' && p.radius === '0px'), `${slug}/${viewport}:面板四边`);
  check(measurement.tables.every(t => t.header === 'rgb(22, 46, 63)' && t.firstBorder === '0px' && t.lastBorder === '0px' && t.lastRowBottom === '0px'), `${slug}/${viewport}:表头与外围无重复边框`);
  check(measurement.tables.filter(table => !table.process).every(table => table.headerHeight >= 26 && table.headerHeight <= 28
    && table.rowHeight >= 37.5 && table.rowHeight <= 39), `${slug}/${viewport}:普通表头与数据行实际高度`);
  check(measurement.processNodes.every(size => size.every(value => value >= 27.4 && value <= 27.8)), `${slug}/${viewport}:工序节点实际尺寸约27.6px`);
  check(measurement.processNodeText.every(node => node.width <= node.available + .5), `${slug}/${viewport}:工序数量完整容纳在圆圈内`);
  await capture(page, `${slug}-${viewport.join('x')}`);
  await validateChartUi(page, slug, viewport);
}

async function interactions(page) {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto(new URL('/boards/production-progress', base).href, { waitUntil: 'networkidle' });
  const input = page.locator('.board-search input');
  await input.fill('DEMO-MO-001');
  await page.waitForFunction(() => document.querySelectorAll('[data-loop-copy]').length === 0);
  check(await page.locator('tbody tr').count() === 1, '进度搜索：单条工单');
  check(await page.locator('[data-loop-copy]').count() === 0, '动态搜索单行无循环副本');
  const scroll = page.locator('.board-table-scroll');
  check(await scroll.evaluate(e => e.scrollHeight <= e.clientHeight), '单行无多余滚动');
  await capture(page, 'progress-single');
  await input.fill('无匹配演示工单');
  check(await page.getByRole('status').textContent() === '暂无匹配工单', '进度搜索：真实空结果');
  check(await page.locator('[data-loop-copy]').count() === 0, '动态搜索空结果无循环副本');
  await capture(page, 'progress-empty');
  await input.fill('');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.waitForFunction(() => document.querySelectorAll('[data-loop-copy]').length === 0);
  check(await page.locator('tbody tr').count() === 12, '清空搜索恢复12条内存数据');
  check(await scroll.evaluate(e => e.scrollHeight > e.clientHeight), '超量内容可滚动');
  await scroll.evaluate(e => { e.scrollTop = e.scrollHeight; });
  check(await page.locator('tbody tr:last-child').evaluate(element => {
    const row = element.getBoundingClientRect();
    const box = element.closest('.board-table-scroll').getBoundingClientRect();
    return row.bottom <= box.bottom + 1 && row.top >= box.top;
  }), '末行实际在滚动视口内可访问');
  await capture(page, 'progress-last-row');
  await page.getByRole('button', { name: '进入全屏', exact: true }).click();
  await page.waitForFunction(() => Boolean(document.fullscreenElement));
  await page.getByRole('button', { name: '退出全屏', exact: true }).waitFor();
  check(await page.getByRole('button', { name: '退出全屏', exact: true }).count() === 1, '浏览器全屏状态同步');
  await page.getByRole('button', { name: '退出全屏', exact: true }).click();
  await page.waitForFunction(() => !document.fullscreenElement);
  await page.getByRole('link', { name: '返回 ERP', exact: true }).click();
  await page.locator('.app-sidebar').waitFor();
  check(await page.locator('.board-page').count() === 0, '返回ERP卸载大屏');
  await page.locator('[data-menu-key="boards"]').click();
  const links = page.locator('[data-flyout-menu-key="boards"] a[target="_blank"]');
  check(await links.count() === 4, '看板菜单四个新标签入口');
  for (const [slug, title] of routes) {
    const link = links.filter({ hasText: title });
    check((await link.getAttribute('rel')).includes('noopener'), `${slug}:noopener`);
    const [popup] = await Promise.all([page.waitForEvent('popup'), link.click()]);
    await popup.locator('.board-page').waitFor();
    check(new URL(popup.url()).pathname === `/boards/${slug}`, `${slug}:新标签真实路由`);
    check(await popup.locator('.app-sidebar').count() === 0, `${slug}:新标签独立布局`);
    await popup.close();
  }
  check(new URL(page.url()).pathname === '/', '原ERP标签保持原页面');
}

(async () => {
  fs.mkdirSync(evidence, { recursive: true });
  try {
    prerequisite(['http:', 'https:'].includes(base.protocol) && !base.username && !base.password && base.pathname === '/' && !base.search && !base.hash, '目标地址合法');
    prerequisite(Boolean(statePath) && fs.existsSync(statePath), '已有真实Session可用');
    prerequisite(!fs.existsSync(browserTemp), '本任务浏览器临时目录未被占用');
    fs.mkdirSync(browserTemp); ownsTemp = true; report.cleanup.created = true;
    process.env.TEMP = browserTemp; process.env.TMP = browserTemp; process.env.TMPDIR = browserTemp;
    check(path.resolve(os.tmpdir()).toLowerCase() === path.resolve(browserTemp).toLowerCase(), 'Playwright实际临时根目录已隔离');
    const executablePath = process.env.BOARDS_QA_BROWSER_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
    prerequisite(fs.existsSync(executablePath), '已安装浏览器可用');
    browser = await chromium.launch({ headless: true, executablePath, env: { ...process.env, TEMP: browserTemp, TMP: browserTemp, TMPDIR: browserTemp } });
    const context = await browser.newContext({ storageState: statePath, viewport: { width: 1920, height: 1080 }, reducedMotion: 'reduce' });
    await protectWrites(context);
    context.on('page', page => page.on('pageerror', error => report.pageErrors.push(error.message)));
    const page = await context.newPage();
    const auth = await context.request.get(new URL('/api/auth/me/', base).href);
    prerequisite(auth.status() === 200 && (await auth.json()).authenticated === true, '真实Session/API登录验证');
    // 无Session的浏览器上下文必须被真实守卫送回登录页，不使用伪造用户绕过认证。
    const anonymous = await browser.newContext();
    await protectWrites(anonymous);
    const guest = await anonymous.newPage();
    await guest.goto(new URL('/boards/production-line', base).href, { waitUntil: 'networkidle' });
    check(new URL(guest.url()).pathname === '/login', '未登录直链重定向登录');
    await anonymous.close();
    for (const viewport of [[1920, 1080], [1366, 768]]) {
      for (const [slug, title, charts] of routes) await validatePage(page, slug, title, charts, viewport);
    }
    await page.setViewportSize({ width: 1920, height: 1080 });
    await interactions(page);
    await motionPages(page);
    check(report.blockedWrites.length === 0, '所有页面零写请求');
    check(report.pageErrors.length === 0, '页面无JavaScript异常');
    report.status = 'PASS';
  } catch (error) {
    report.status = error.blocked ? 'BLOCKED' : 'FAIL';
    report.failure = String(error.message).replace(/https?:\/\/[^\s]+/g, '[URL]');
  } finally {
    try { if (browser) await browser.close(); report.cleanup.closed = true; }
    catch (error) { report.status = 'FAIL'; report.cleanup.error = `浏览器关闭失败：${error.message}`; }
    if (ownsTemp && report.cleanup.closed) {
      const expected = path.resolve(root, '.tmp/boards_20261016/browser');
      if (path.resolve(browserTemp) !== expected) { report.status = 'FAIL'; report.cleanup.error = '临时路径归属校验失败'; }
      else {
        try { fs.rmSync(browserTemp, { recursive: true }); report.cleanup.removed = true; report.cleanup.verifiedAbsent = !fs.existsSync(browserTemp); }
        catch (error) { report.status = 'FAIL'; report.cleanup.error = `临时目录清理失败：${error.message}`; }
      }
    }
    for (const [name, value] of Object.entries(previousTemp)) {
      if (value === undefined) delete process.env[name]; else process.env[name] = value;
    }
    save();
    console.log(JSON.stringify({ qa_result_version: 1, status: report.status, not_covered: report.not_covered,
      failure: report.failure ? { message: report.failure } : undefined,
      checks: report.checks.length, report: path.relative(root, path.join(evidence, 'report.json')),
      cleanup: report.cleanup.closed && report.cleanup.verifiedAbsent }));
    process.exitCode = report.status === 'PASS' ? 0 : report.status === 'BLOCKED' ? 2 : 1;
  }
})();
