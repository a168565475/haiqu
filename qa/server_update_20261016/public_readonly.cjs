// Public deployment smoke: GET/HEAD only, no credentials, no business mutations.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const https = require('node:https');

const root = path.resolve(__dirname, '../..');
const erp = 'https://erp.cnhitree.com';
const crm = 'https://crm.cnhitree.com';
const plan = {
  mode: 'headless-read-only',
  allowedMethods: ['GET', 'HEAD'],
  loginPage: `${erp}/login`,
  actualFrontendAuthRequest: `${erp}/api/auth/me/`,
  protectedApi: `${erp}/api/v1/customers/`,
  erpHealth: `${erp}/api/health/`,
  crmHealth: `${crm}/api/health`,
  csrfScope: 'Check cookie metadata and JavaScript visibility; do not POST.',
};

if (!process.argv.includes('--run')) {
  console.log(JSON.stringify(plan, null, 2));
} else {
  run().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

function safeUrl(value) {
  const url = new URL(value);
  return `${url.origin}${url.pathname}`;
}

function request(url) {
  return new Promise((resolve, reject) => {
    const transport = url.startsWith('https:') ? https : http;
    const req = transport.get(url, { timeout: 20000 }, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => {
        body += chunk;
        if (body.length > 1024 * 1024) response.destroy(new Error('Response exceeded 1 MiB.'));
      });
      response.on('error', reject);
      response.on('end', () => resolve({ status: response.statusCode, headers: response.headers, body }));
    });
    req.on('timeout', () => req.destroy(new Error(`GET timeout: ${safeUrl(url)}`)));
    req.on('error', reject);
  });
}

function jsonBody(response) {
  try { return JSON.parse(response.body); } catch { return null; }
}

async function run() {
  const { chromium } = require('playwright');
  const runId = `${new Date().toISOString().replace(/[:.]/g, '-')}-${process.pid}`;
  const reportDir = path.join(root, 'output', 'playwright', `erp-public-readonly-${runId}`);
  const temporaryRoot = path.join(reportDir, 'temporary');
  const profile = path.join(temporaryRoot, 'profile');
  const temp = path.join(temporaryRoot, 'temp');
  const resourcePath = path.join(__dirname, `public_readonly_${runId}_resources.json`);
  const reportPath = path.join(reportDir, 'report.json');
  const screenshotPath = path.join(reportDir, 'erp-login-1920x1080.png');
  const report = {
    startedAt: new Date().toISOString(), plan, checks: [],
    pageErrors: [], consoleErrors: [], consoleWarnings: [], requestFailures: [],
    blockedRequests: [], pageResponses: [], insecureRequests: [], webSockets: [],
    notExecuted: ['Authenticated account/business acceptance', 'POST CSRF rejection', 'Session-cookie runtime attributes after login'],
  };
  const resources = {
    task: 'ERP public headless read-only deployment acceptance',
    runId, createdAt: report.startedAt,
    retainedEvidence: [resourcePath, reportPath, screenshotPath],
    temporary: [temporaryRoot, profile, temp].map((target) => ({
      path: target, existedBefore: fs.existsSync(target), created: false, deleted: false,
      cleanup: 'Close the task browser, verify the exact absolute task path, remove it and recheck absence.',
    })),
  };
  if (resources.temporary.some((item) => item.existedBefore)) throw new Error('Task temporary path already exists.');
  const writeResources = () => fs.writeFileSync(resourcePath, JSON.stringify(resources, null, 2));
  const check = (name, pass, evidence) => report.checks.push({ name, status: pass ? 'PASS' : 'FAIL', evidence });
  // The resource list is persisted before creating the browser profile or TEMP/TMP.
  writeResources();
  const originalTemp = { TEMP: process.env.TEMP, TMP: process.env.TMP };
  let context;
  let authResult;
  try {
    fs.mkdirSync(reportDir, { recursive: true });
    for (const item of resources.temporary) {
      fs.mkdirSync(item.path);
      item.created = true;
      writeResources();
    }
    process.env.TEMP = temp;
    process.env.TMP = temp;

    const redirect = await request('http://erp.cnhitree.com/login');
    check('http-to-https', [301, 308].includes(redirect.status) && redirect.headers.location === `${erp}/login`, {
      status: redirect.status, location: redirect.headers.location,
    });
    const erpHealth = await request(plan.erpHealth);
    const erpStatus = jsonBody(erpHealth);
    check('erp-health', erpHealth.status === 200 && erpStatus?.status === 'ok' && erpStatus.database === 'ok' && erpStatus.redis === 'ok', {
      status: erpHealth.status, service: erpStatus?.service, database: erpStatus?.database, redis: erpStatus?.redis,
    });
    const crmHealth = await request(plan.crmHealth);
    const crmStatus = jsonBody(crmHealth);
    check('crm-health-unchanged', crmHealth.status === 200 && crmStatus?.status === 'ok', {
      status: crmHealth.status, health: crmStatus?.status,
    });
    const protectedApi = await request(plan.protectedApi);
    check('unauthenticated-api-denied', protectedApi.status === 401 && /application\/json/.test(protectedApi.headers['content-type'] || ''), {
      status: protectedApi.status, authenticate: protectedApi.headers['www-authenticate'],
    });
    const media = await request(`${erp}/media/`);
    check('media-not-public', media.status === 404, { status: media.status });
    const adminCss = await request(`${erp}/static/admin/css/base.css`);
    check('collected-static-css', adminCss.status === 200 && /text\/css/.test(adminCss.headers['content-type'] || ''), {
      status: adminCss.status, contentType: adminCss.headers['content-type'],
    });

    context = await chromium.launchPersistentContext(profile, {
      executablePath: process.env.UI_E2E_BROWSER_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
      headless: true, viewport: { width: 1920, height: 1080 },
      ignoreHTTPSErrors: false, serviceWorkers: 'block',
    });
    await context.route('**/*', async (route) => {
      const outgoing = route.request();
      const url = new URL(outgoing.url());
      if (!plan.allowedMethods.includes(outgoing.method()) || url.origin !== erp) {
        report.blockedRequests.push({ method: outgoing.method(), url: safeUrl(outgoing.url()) });
        await route.abort('blockedbyclient');
      } else {
        await route.continue();
      }
    });
    const page = context.pages()[0] || await context.newPage();
    const securitySession = await context.newCDPSession(page);
    securitySession.on('Security.visibleSecurityStateChanged', ({ visibleSecurityState: state }) => {
      const certificate = state.certificateSecurityState || {};
      report.chromeSecurityState = {
        state: state.securityState, issueIds: state.securityStateIssueIds,
        protocol: certificate.protocol, subjectName: certificate.subjectName,
        issuer: certificate.issuer, validFrom: certificate.validFrom, validTo: certificate.validTo,
        certificateNetworkError: certificate.certificateNetworkError,
        modernSSL: certificate.modernSSL,
      };
    });
    await securitySession.send('Security.enable');
    page.on('pageerror', (error) => report.pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') report.consoleErrors.push(message.text());
      if (message.type() === 'warning') report.consoleWarnings.push(message.text());
    });
    page.on('request', (outgoing) => {
      if (/^(http|ws):/.test(outgoing.url())) report.insecureRequests.push(safeUrl(outgoing.url()));
    });
    page.on('websocket', (socket) => report.webSockets.push(safeUrl(socket.url())));
    page.on('requestfailed', (failed) => report.requestFailures.push({
      url: safeUrl(failed.url()), error: failed.failure()?.errorText,
    }));
    page.on('response', (response) => report.pageResponses.push({
      url: safeUrl(response.url()), status: response.status(), type: response.request().resourceType(),
    }));
    const actualAuth = page.waitForResponse((response) => response.url() === plan.actualFrontendAuthRequest && response.request().method() === 'GET', { timeout: 20000 })
      .then((response) => ({ response }), (error) => ({ error }));
    const navigation = await page.goto(`${erp}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const authOutcome = await actualAuth;
    if (authOutcome.error) throw authOutcome.error;
    const authResponse = authOutcome.response;
    authResult = await authResponse.json();
    await page.locator('#login-username').waitFor({ state: 'visible', timeout: 20000 });
    await page.waitForLoadState('networkidle', { timeout: 20000 });
    report.tls = await navigation.securityDetails();
    report.serverAddress = await navigation.serverAddr();
    report.browserSecurity = await page.evaluate(() => ({
      isSecureContext: window.isSecureContext,
      protocol: window.location.protocol,
      insecureResources: performance.getEntriesByType('resource')
        .map((entry) => entry.name).filter((url) => /^(http|ws):/.test(url)),
      insecureDomReferences: Array.from(document.querySelectorAll('script[src], img[src], link[href], iframe[src], audio[src], video[src], source[src]'))
        .map((element) => element.src || element.href || '').filter((url) => /^(http|ws):/.test(url)),
    }));
    const securityMessages = [...report.consoleErrors, ...report.consoleWarnings]
      .filter((message) => /mixed content|certificate|ERR_CERT|insecure|security/i.test(message));
    check('browser-https-security', report.browserSecurity.isSecureContext && report.tls?.protocol?.startsWith('TLS')
      && report.insecureRequests.length === 0 && report.browserSecurity.insecureResources.length === 0
      && report.browserSecurity.insecureDomReferences.length === 0 && securityMessages.length === 0
      && (!report.chromeSecurityState || report.chromeSecurityState.state === 'secure'), {
      tls: report.tls, chromeSecurityState: report.chromeSecurityState,
      browserSecurity: report.browserSecurity, insecureRequests: report.insecureRequests,
      webSockets: report.webSockets, securityMessages,
    });
    const accountField = await page.locator('#login-username').isVisible();
    const passwordField = await page.locator('#login-password').isVisible();
    const loginButton = await page.getByRole('button', { name: '登录', exact: true }).isVisible();
    check('spa-root-and-login', navigation.status() === 200 && new URL(page.url()).pathname === '/login' && accountField && passwordField && loginButton, {
      status: navigation.status(), finalUrl: safeUrl(page.url()),
      accountField, passwordField, loginButton,
    });
    check('actual-same-origin-auth-request', authResponse.status() === 200 && authResult.authenticated === false && authResult.user === null, {
      url: safeUrl(authResponse.url()), status: authResponse.status(), authenticated: authResult.authenticated,
    });
    const cookies = await context.cookies(erp);
    const csrf = cookies.find((cookie) => cookie.name === 'csrftoken');
    const csrfReadable = await page.evaluate(() => document.cookie.split(';').some((item) => item.trim().startsWith('csrftoken=')));
    check('csrf-cookie-metadata', Boolean(csrf?.secure && !csrf.httpOnly && csrf.sameSite === 'Lax' && csrf.domain === 'erp.cnhitree.com' && csrfReadable), {
      present: Boolean(csrf), secure: csrf?.secure, httpOnly: csrf?.httpOnly,
      sameSite: csrf?.sameSite, domain: csrf?.domain, readableByJavaScript: csrfReadable,
    });
    const assets = report.pageResponses.filter((response) => new URL(response.url).pathname.startsWith('/assets/'));
    check('frontend-static-resources', assets.some((asset) => asset.type === 'script') && assets.some((asset) => asset.type === 'stylesheet') && assets.every((asset) => asset.status === 200), assets);
    check('browser-errors', report.pageErrors.length === 0 && report.consoleErrors.length === 0 && report.requestFailures.length === 0 && report.blockedRequests.length === 0 && report.pageResponses.every((response) => response.status < 400), {
      pageErrors: report.pageErrors, consoleErrors: report.consoleErrors,
      requestFailures: report.requestFailures, blockedRequests: report.blockedRequests,
    });
    await page.screenshot({ path: screenshotPath, fullPage: true });
  } catch (error) {
    check('execution', false, { message: error.message });
  } finally {
    report.finishedAt = new Date().toISOString();
    if (fs.existsSync(reportDir)) fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
    let browserClosed = true;
    if (context) {
      try { await context.close(); } catch (error) {
        browserClosed = false;
        check('browser-close', false, { message: error.message });
      }
    }
    for (const [name, value] of Object.entries(originalTemp)) {
      if (value === undefined) delete process.env[name]; else process.env[name] = value;
    }
    for (const item of [...resources.temporary].reverse()) {
      try {
        if (!browserClosed) throw new Error('Browser closure is unverified; do not delete occupied resources.');
        const resolved = path.resolve(item.path);
        if (resolved !== item.path || (resolved !== temporaryRoot && !resolved.startsWith(`${temporaryRoot}${path.sep}`))) throw new Error('Cleanup boundary check failed.');
        if (item.created && fs.existsSync(resolved)) {
          if (resolved === temporaryRoot) fs.rmdirSync(resolved);
          else fs.rmSync(resolved, { recursive: true, force: false });
        }
        item.deleted = !fs.existsSync(resolved);
      } catch (error) { item.cleanupError = error.message; }
    }
    resources.finishedAt = new Date().toISOString();
    writeResources();
    check('temporary-resource-cleanup', resources.temporary.every((item) => item.deleted), resources.temporary);
    report.summary = report.checks.some((item) => item.status === 'FAIL') ? 'FAIL' : 'PASS';
    fs.mkdirSync(reportDir, { recursive: true });
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ summary: report.summary, reportPath, resourcePath, checks: report.checks.map(({ name, status }) => ({ name, status })) }, null, 2));
    process.exitCode = report.summary === 'PASS' ? 0 : 1;
  }
}
