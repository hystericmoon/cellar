const { chromium } = require('playwright'); const fs = require('fs');
const R = '/storage/emulated/0';
const ok = (c, m) => console.log((c ? 'PASS ' : 'FAIL ') + m);
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1360,height:820}});
  await ctx.grantPermissions(['clipboard-read','clipboard-write'], {origin:'http://127.0.0.1:8765'});
  const p = await ctx.newPage(); const errs=[]; p.on('pageerror', x=>errs.push(x.message)); p.on('console', m => m.type()==='error' && !/502|409|400/.test(m.text()) && errs.push(m.text()));
  const rows = () => p.$$eval('button.name .nm', b => b.map(x => x.textContent));
  const row = n => `tr:has(button.name:has-text("${n}"))`;
  const step = async (name, fn) => { try { await fn(); } catch (e) { ok(false, name + ' threw: ' + e.message.split('\n')[0]); await p.screenshot({path:__dirname + '/shots/fail-' + name.replace(/\W+/g,'_') + '.png'}); } };
  await p.goto('http://127.0.0.1:8765/'); await p.waitForSelector('table'); await p.click('[data-view=list]');
  await p.click('nav button[data-path$="/Download"]'); await p.waitForSelector(row('report.pdf'));

  await step('menu', async () => {
    await p.click(row('report.pdf') + ' button.name', {button:'right'}); await p.waitForSelector('#ctxmenu:not([hidden])');
    const items = await p.$$eval('#ctxmenu [role=menuitem]', b => b.map(x => x.firstChild.textContent));
    ok(items.includes('Cut') && items.includes('Rename') && items.includes('Move to Trash'), 'context menu items: ' + items.join(' | '));
    ok(await p.evaluate(() => document.activeElement.getAttribute('role') === 'menuitem'), 'focus moves into menu');
    await p.keyboard.press('ArrowDown'); await p.keyboard.press('Escape');
    ok(await p.$eval('#ctxmenu', m => m.hidden) && await p.evaluate(() => !!document.activeElement.closest('[data-row]')), 'Esc closes menu, focus returns to row');
  });
  await step('copy-conflict', async () => {
    await p.click(row('report.pdf') + ' button.name', {modifiers:['Control']});
    await p.keyboard.press('Control+c'); await p.waitForSelector('#hint:not([hidden])');
    ok((await p.textContent('#hint')).includes('copied'), 'hint shows copied');
    await p.click('nav button[data-path$="/Documents"]'); await p.waitForSelector(row('notes.txt'));
    await p.keyboard.press('Control+v'); await p.waitForSelector('#conflict[open]');
    ok((await p.textContent('#cfTitle')).includes('report.pdf'), 'conflict dialog: ' + await p.textContent('#cfTitle'));
    await p.screenshot({path:__dirname + '/shots/u2.png'});
    await p.click('[data-cf=new]'); await p.waitForSelector(row('report 2.pdf'), {timeout:8000});
    ok(fs.existsSync(R + '/Documents/report 2.pdf'), 'keep both created "report 2.pdf"');
  });
  await step('cut-paste-undo', async () => {
    await p.click(row('notes.txt') + ' button.name', {modifiers:['Control']}); await p.keyboard.press('Control+x');
    ok(await p.$eval(row('notes.txt'), r => r.classList.contains('cut')), 'cut row is faded');
    await p.click(row('Work') + ' button.name'); await p.waitForSelector(row('plan.txt'));
    await p.keyboard.press('Control+v'); await p.waitForSelector(row('notes.txt'), {timeout:8000});
    ok(fs.existsSync(R + '/Documents/Work/notes.txt') && !fs.existsSync(R + '/Documents/notes.txt'), 'cut + paste moved the file');
    await p.waitForSelector('.toast:has-text("Moved")'); await p.click('.toast:has-text("Moved") button');
    await p.waitForTimeout(2500); ok(fs.existsSync(R + '/Documents/notes.txt'), 'Undo moved it back');
  });
  await step('rename-newfolder-trash', async () => {
    await p.click('#crumbs button:has-text("Documents")'); await p.waitForSelector(row('notes.txt'));
    await p.click(row('notes.txt') + ' button.name', {modifiers:['Control']}); await p.keyboard.press('F2');
    await p.waitForSelector('input.rename'); await p.keyboard.press('Control+a'); await p.keyboard.type('groceries.txt'); await p.keyboard.press('Enter');
    await p.waitForSelector(row('groceries.txt')); ok(fs.existsSync(R + '/Documents/groceries.txt'), 'F2 rename');
    await p.keyboard.press('Control+z'); await p.waitForSelector(row('notes.txt'), {timeout:5000}); ok(fs.existsSync(R + '/Documents/notes.txt'), 'Ctrl+Z undid rename');
    await p.click('#newFolderBtn'); await p.waitForSelector('input.rename'); await p.keyboard.type('Bali photos'); await p.keyboard.press('Enter');
    await p.waitForSelector(row('Bali photos')); ok(fs.existsSync(R + '/Documents/Bali photos'), 'new folder + name');
    await p.click(row('report 2.pdf') + ' button.name', {modifiers:['Control']}); await p.keyboard.press('Control+Backspace');
    await p.waitForSelector('.toast:has-text("Trash")'); ok(!fs.existsSync(R + '/Documents/report 2.pdf'), 'Ctrl+Backspace moved to Trash');
    await p.screenshot({path:__dirname + '/shots/u3.png'});
    await p.click('#library button[data-lib=trash]'); await p.waitForSelector(row('report 2.pdf'));
    ok((await p.textContent(row('report 2.pdf'))).includes('Documents'), 'Trash shows original location');
    await p.click(row('report 2.pdf') + ' [data-putback]'); await p.waitForSelector('.toast:has-text("Put back")');
    ok(fs.existsSync(R + '/Documents/report 2.pdf'), 'Put back restored it');
  });
  await step('drag-move', async () => {
    await p.click('nav button[data-path$="/Documents"]'); await p.waitForSelector(row('Bali photos'));
    await p.dragAndDrop(row('report 2.pdf'), row('Bali photos')); await p.waitForTimeout(2500);
    ok(fs.existsSync(R + '/Documents/Bali photos/report 2.pdf'), 'drag onto folder moved the file');
  });
  await step('search-recent', async () => {
    await p.click('#filter'); await p.keyboard.type('invoice'); await p.waitForSelector('#hint:has-text("whole phone")');
    await p.keyboard.press('Enter'); await p.waitForSelector(row('Invoice-Oct.pdf'));
    ok((await p.textContent(row('Invoice-Oct.pdf'))).includes('Download'), 'whole-phone search with Where column');
    await p.click('#library button[data-lib=recent]'); await p.waitForSelector('#crumbs:has-text("Recent")'); await p.waitForTimeout(800); ok((await rows()).length > 3, 'Recent view lists files');
  });
  await step('save', async () => {
    await p.click('#library button[data-lib=recent]'); await p.waitForSelector(row('Invoice-Oct.pdf'));
    await p.click(row('Invoice-Oct.pdf') + ' [data-save]'); await p.waitForSelector('#txList li:has-text("Invoice-Oct.pdf"):has-text("Done")', {timeout:8000});
    ok(fs.existsSync(process.env.HOME + '/Downloads/Cellar/Invoice-Oct.pdf'), 'Save to Mac via transfer queue');
  });
  await step('upload', async () => {
    await p.click('nav button[data-path$="/Documents"]'); await p.waitForSelector(row('Work'));
    await p.setInputFiles('#folderInput', process.argv[2]); await p.waitForSelector(row('SocSaver'), {timeout:10000});
    ok(fs.existsSync(R + '/Documents/SocSaver/Saved posts/2026/two.jpg'), 'folder upload through staging + push job');
    await p.setInputFiles('#folderInput', process.argv[2]); await p.waitForSelector('#conflict[open]'); ok((await p.textContent('#cfReplace')) === 'Merge', 'folder conflict offers Merge');
    await p.click('[data-cf=replace]'); await p.waitForTimeout(2500); ok(!fs.existsSync(R + '/Documents/SocSaver 2'), 'merge did not create a copy');
    await p.screenshot({path:__dirname + '/shots/u4.png'});
  });
  await step('backup-apps', async () => {
    await p.click('#library button[data-lib=backup]'); await p.waitForSelector('#bkRun');
    ok(/photo/.test(await p.textContent('#bkNow')), 'backup view: ' + await p.textContent('#bkNow'));
    await p.screenshot({path:__dirname + '/shots/u5.png'});
    await p.click('#bkRun'); await p.waitForSelector('#bkNow:has-text("Everything is backed up")', {timeout:10000}); ok(true, 'backup ran, view refreshed');
    await p.click('#library button[data-lib=apps]'); await p.waitForSelector('[data-appsave]'); ok((await p.$$('[data-appsave]')).length === 2, 'apps listed');
    await p.screenshot({path:__dirname + '/shots/u6.png'});
    await p.click('[data-appdel]'); await p.waitForSelector('#confirm[open]'); ok((await p.textContent('#cnTitle')).startsWith('Uninstall'), 'uninstall asks first'); await p.click('#cnCancel');
  });
  await step('timeline-mirror', async () => {
    await p.click('nav button[data-path$="/Camera"]'); await p.waitForSelector('.grid .dayhead'); ok(true, 'Camera opens as photo timeline');
    await p.screenshot({path:__dirname + '/shots/u7.png'});
    await p.click('#mirrorBtn'); await p.waitForSelector('#mrInstall'); ok(true, 'mirror offers scrcpy download'); await p.click('#mrClose');
  });
  await step('dark-menu', async () => {
    await p.emulateMedia({colorScheme:'dark'}); await p.click('nav button[data-path$="/Documents"]'); await p.click('[data-view=list]'); await p.waitForSelector(row('Work'));
    await p.click('#content', {button:'right', position:{x:600, y:560}}); await p.waitForSelector('#ctxmenu:not([hidden])'); await p.screenshot({path:__dirname + '/shots/u8.png'});
  });
  await step('restyle', async () => {
    await p.emulateMedia({colorScheme:'light'}); await p.click('[data-view=list]'); await p.waitForSelector(row('Work'));
    const css = await p.evaluate(() => { const g = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim(); return {text:g('--text'), muted:g('--muted'), line:g('--line'), accent:g('--accent')}; });
    ok(css.text === '#09090b' && css.muted === '#71717a' && css.line === '#e4e4e7' && css.accent === '#18181b', 'zinc tokens in light mode');
    await p.click(row('Work') + ' td.ck input.sel', {force:true});
    const sel = await p.$eval(row('Work') + ' td:first-child', td => ({shadow:getComputedStyle(td).boxShadow, box:td.querySelector('input.sel').checked}));
    ok(sel.box && sel.shadow !== 'none', 'selected row has a checkmark and a left border, not just a fill');
    await p.keyboard.press('Escape');
    await p.emulateMedia({colorScheme:'dark'}); await p.waitForTimeout(100);
    ok(await p.evaluate(() => getComputedStyle(document.body).backgroundColor) === 'rgb(9, 9, 11)', 'dark mode is zinc-950');
    await p.emulateMedia({colorScheme:'light'});
  });
  console.log('errors:', errs); await b.close();
})();
