const { chromium } = require('@playwright/test');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', err => errors.push(err.message));
  
  console.log('Navigating to login...');
  try {
      await page.goto('http://127.0.0.1:4180/');
  } catch(e) {
      console.log('Cannot connect to dev server on 4180');
      await browser.close();
      return;
  }
  
  await page.waitForTimeout(2000);
  console.log('Current URL:', page.url());
  
  try {
    const emailInput = await page.$('input[type="email"], input[name="email"]');
    if (emailInput) {
        await emailInput.fill('dramaforge.owner@example.com');
        await page.fill('input[type="password"]', 'professional-proof-password-2026');
        await page.click('button[type="submit"]');
        console.log('Submitted login form');
        await page.waitForTimeout(3000);
    } else {
        console.log('Could not find login form');
    }
  } catch (e) {
    console.log('Error during login:', e.message);
  }
  
  console.log('Current URL after login attempt:', page.url());
  
  await page.screenshot({ path: 'd:/dramaforge/frontend/screenshot.png', fullPage: true });
  console.log('Screenshot saved to d:/dramaforge/frontend/screenshot.png');
  console.log('Errors:', errors);
  await browser.close();
})();
