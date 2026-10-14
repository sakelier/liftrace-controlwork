async page => {
  await page.evaluate(()=>localStorage.clear());await page.reload();
  const competition=page.locator('.grp-card').filter({hasText:'独立正赛 · 10×10 实测场地'});
  await competition.locator('[data-option=competitionPreset]').selectOption('deployment/competition/field_20261007_validated.yaml');
  await competition.getByRole('button',{name:'地图调整航点',exact:true}).click();
  const frame=page.frameLocator('iframe[title="航点地图与坐标微调"]');
  await frame.locator('#map circle[data-kind=corridor]').nth(6).waitFor();
  if(await frame.locator('#map circle[data-kind=corridor]').count()!==7)throw Error('wrong competition route');
  await frame.locator('[data-mode=landing]').click();
  await frame.getByRole('spinbutton',{name:'H 降落点 X'}).fill('7.6');
  await frame.locator('#export').click();
  await page.waitForFunction(()=>Object.keys(groupUI(state.groups.find(g=>g.id==='competition')).geometryPlans||{}).length===3);
  if(!await page.evaluate(()=>groupUI(state.groups.find(g=>g.id==='competition')).geometryValues.landing_xy[0]===7.6))throw Error('save mapping failed');
  if(!await page.evaluate(()=>trialBody(state.groups.find(g=>g.id==='competition'),'flight',false).expected_body.includes('competition_')))throw Error('wrong flight overlay');
  if(!await page.evaluate(()=>!state.trial.group_id))throw Error('unexpected flight');
  await competition.getByRole('button',{name:'地图调整航点',exact:true}).click();
  await frame.locator('#map circle[data-kind=landing]').waitFor();
  const competitionPath=await page.locator('iframe[title="航点地图与坐标微调"]').getAttribute('src');
  await page.getByRole('dialog').getByRole('button',{name:'关闭',exact:true}).click();
  if(!await page.evaluate(()=>!!window.WaypointWorkbench))return;
  // Use its existing public adapter to avoid depending on translated card titles.
  await page.evaluate(()=>{const g=state.groups.find(g=>g.id==='mod08');state.selectedGroup=g.id;renderGroups();});
  const button=page.locator('.grp-card.sel').getByRole('button',{name:'地图调整航点',exact:true});
  await button.click();await frame.locator('#map circle[data-kind=corridor]').first().waitFor();
  const modulePath=await page.locator('iframe[title="航点地图与坐标微调"]').getAttribute('src');
  if(modulePath!==competitionPath)throw Error('different map components');
  await frame.locator('[data-mode=landing]').click();
  await frame.getByRole('spinbutton',{name:'H 降落点 X'}).fill('7.6');
  await frame.locator('#undo').click();
  await page.getByRole('dialog').getByRole('button',{name:'关闭',exact:true}).click();
}