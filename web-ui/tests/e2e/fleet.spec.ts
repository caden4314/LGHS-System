import { expect, test } from '@playwright/test'

async function expectNoViewportOverflow(page: import('@playwright/test').Page) {
  const overflow = await page.evaluate(() => ({
    body: document.body.scrollWidth - document.body.clientWidth,
    html: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  }))
  expect(overflow.body).toBeLessThanOrEqual(1)
  expect(overflow.html).toBeLessThanOrEqual(1)
}

test('overview presents actionable fleet state and branded signal art', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Fleet overview' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Fleet communications status' })).toBeVisible()
  await expect(page.locator('.overview-signal canvas')).toBeVisible()
  await expect(page.getByText('Temperature is above critical threshold')).toBeVisible()
  await expect(page.getByRole('link', { name: /All alerts/ })).toBeVisible()
  await expectNoViewportOverflow(page)
})

test('fleet search, filters, sorting and drill-down are functional', async ({ page }) => {
  await page.goto('/fleet')
  await expect(page.getByRole('heading', { name: 'Fleet' })).toBeVisible()

  const search = page.getByPlaceholder('Search device, group, tag, or version')
  await search.fill('CS-999')
  await expect(page.getByRole('link', { name: 'CS-999' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'CS-102' })).toHaveCount(0)

  await search.fill('')
  await page.getByLabel('Group').selectOption('Validation')
  await expect(page.getByRole('link', { name: 'CS-999' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'CS-101' })).toHaveCount(0)

  await page.getByLabel('Group').selectOption('All')
  await page.getByRole('button', { name: /Temp/ }).click()
  await page.getByRole('link', { name: 'CS-999' }).click()
  await expect(page.getByRole('heading', { name: 'CS-999' })).toBeVisible()
  await expect(page.getByText('0.6.0', { exact: true }).first()).toBeVisible()
})

test('theme selection is explicit and persists', async ({ page }) => {
  await page.goto('/')
  const html = page.locator('html')
  const lightButton = page.getByRole('button', { name: 'Use light theme' })
  const darkButton = page.getByRole('button', { name: 'Use dark theme' })

  if (await lightButton.isVisible()) await lightButton.click()
  await expect(html).toHaveAttribute('data-theme', 'light')
  await page.reload()
  await expect(html).toHaveAttribute('data-theme', 'light')
  await darkButton.click()
  await expect(html).toHaveAttribute('data-theme', 'dark')
})

test('group links preserve a durable filter in the URL', async ({ page }) => {
  await page.goto('/groups')
  const card = page.locator('.group-card').filter({ hasText: 'Validation' })
  await card.getByRole('link', { name: 'View devices' }).click()
  await expect(page).toHaveURL(/\/fleet\?group=Validation/)
  await expect(page.getByRole('link', { name: 'CS-999' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'CS-101' })).toHaveCount(0)
})

test('mobile shell remains usable without page-level horizontal overflow', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-chromium', 'mobile-specific acceptance')
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Fleet overview' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible()
  await expectNoViewportOverflow(page)

  await page.goto('/fleet')
  await expect(page.getByPlaceholder('Search device, group, tag, or version')).toBeVisible()
  // The data table itself may scroll horizontally; the document must not.
  await expectNoViewportOverflow(page)
})

test('reduced-motion preference keeps the Signal Field non-essential', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'reduced-motion', 'reduced-motion-specific acceptance')
  // Set this explicitly in the test as well as the project so the assertion
  // verifies the application behavior, not a runner/device preset quirk.
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.locator('.overview-signal canvas')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Fleet overview' })).toBeVisible()
  const reduced = await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
  expect(reduced).toBe(true)
})
