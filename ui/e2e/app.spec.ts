import { expect, test, type Page } from "@playwright/test";

// Browser end-to-end tests. Each title starts with its ID from docs/TEST_CASES.md.
// They run in order against one isolated server (e2e/start-server.sh).

const ADMIN = { email: "admin@vireoka.com", password: "admin-pass-123" };
const UMA = { email: "uma@vireoka.com", password: "user-pass-1234" };
const OTTO = { email: "otto@vireoka.com", password: "user-pass-1234" };

async function login(page: Page, who: { email: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(who.email);
  await page.getByLabel("Password", { exact: true }).fill(who.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Good (morning|afternoon|evening)/);
}

test.describe.serial("Vanguard-GTM web app", () => {
  test("UI-01 wrong password is refused and protected pages redirect to sign-in", async ({ page }) => {
    await page.goto("/campaigns");
    await expect(page).toHaveURL(/\/login$/);
    await page.getByLabel("Email", { exact: true }).fill(UMA.email);
    await page.getByLabel("Password", { exact: true }).fill("wrong-password");
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByRole("alert")).toContainText("wrong email or password");
  });

  test("UI-02 general user sees the dashboard but no Admin area", async ({ page }) => {
    await login(page, UMA);
    await expect(page.getByRole("heading", { name: "Properties" })).toBeVisible();
    await expect(page.locator("h3", { hasText: "OratoPlus" })).toBeVisible();
    await expect(page.locator("h3.font-serif")).toHaveCount(8);
    await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Admin" })).toHaveCount(0);
    await page.goto("/admin");
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("button", { name: /Edit target/ })).toHaveCount(0);
  });

  test("UI-03 user creates a campaign, logs results and sees the totals", async ({ page }) => {
    await login(page, UMA);
    await page.getByRole("link", { name: "Campaigns" }).first().click();
    await page.getByRole("button", { name: "New campaign" }).first().click();
    const dlg = page.getByRole("dialog", { name: "New campaign" });
    await dlg.getByLabel("Name", { exact: true }).fill("Founders demo-day sparring push");
    await dlg.getByLabel("Property", { exact: true }).selectOption("oratoplus");
    await dlg.getByLabel("Status", { exact: true }).selectOption("active");
    await dlg.getByLabel("Goal value", { exact: true }).fill("20");
    await dlg.getByRole("button", { name: "Create campaign" }).click();
    await expect(page.getByRole("heading", { name: "Founders demo-day sparring push" })).toBeVisible();

    await page.getByRole("button", { name: "Log results" }).click();
    const r = page.getByRole("dialog", { name: "Log results" });
    await r.getByLabel("Sent", { exact: true }).fill("120");
    await r.getByLabel("Replies", { exact: true }).fill("9");
    await r.getByLabel("Meetings", { exact: true }).fill("4");
    await r.getByLabel("Conversions", { exact: true }).fill("2");
    await r.getByLabel("Revenue ($)", { exact: true }).fill("50");
    await r.getByRole("button", { name: "Save results" }).click();
    await expect(page.getByText("Results logged")).toBeVisible();
    await expect(page.getByText("7.5% reply rate")).toBeVisible();
    await expect(page.getByText("Goal: 20 Meetings")).toBeVisible();
    await expect(page.getByText("4 (20.0%)")).toBeVisible();

    await page.getByLabel("Status", { exact: true }).selectOption("paused");
    await expect(page.getByText("Status: Paused")).toBeVisible();
    await page.goto("/campaigns?status=paused");
    await expect(page.getByRole("link", { name: "Founders demo-day sparring push" })).toBeVisible();
  });

  test("UI-04 another user can edit but not delete someone else's campaign", async ({ page }) => {
    await login(page, OTTO);
    await page.goto("/campaigns");
    await page.getByRole("link", { name: "Founders demo-day sparring push" }).click();
    await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete" })).toHaveCount(0);
  });

  test("UI-05 user adds a design partner, logs a call that moves the stage, and moves it on the board", async ({ page }) => {
    await login(page, UMA);
    await page.getByRole("link", { name: "Partners" }).first().click();
    await page.getByRole("button", { name: "Add partner" }).first().click();
    const dlg = page.getByRole("dialog", { name: "Add partner" });
    await dlg.getByLabel("Organisation", { exact: true }).fill("Northstar Accelerator");
    await dlg.getByLabel("Property", { exact: true }).selectOption("oratoplus");
    await dlg.getByLabel("Partnership type", { exact: true }).selectOption("design_partner");
    await dlg.getByRole("button", { name: "Add partner" }).click();
    await expect(page.getByRole("heading", { name: "Northstar Accelerator" })).toBeVisible();

    await page.getByLabel("What happened", { exact: true }).fill("Intro call with the program director - keen on a 6-week pilot.");
    await page.getByLabel("Type", { exact: true }).selectOption("call");
    await page.getByLabel("Outcome", { exact: true }).selectOption("positive");
    await page.getByLabel("Move stage to", { exact: true }).selectOption("in_conversation");
    await page.getByRole("button", { name: "Log interaction" }).click();
    await expect(page.getByText("keen on a 6-week pilot")).toBeVisible();
    await expect(page.locator("[aria-current=step]")).toContainText("In conversation");

    await page.goto("/partners?property=oratoplus&view=board");
    const card = page.locator("article", { hasText: "Northstar Accelerator" });
    await expect(page.getByRole("region", { name: "In conversation" }).locator("article", { hasText: "Northstar" })).toBeVisible();
    await card.getByLabel("Move Northstar Accelerator", { exact: true }).selectOption("pilot");
    await expect(page.getByRole("region", { name: "Pilot" }).locator("article", { hasText: "Northstar" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("region", { name: "Pilot" }).locator("article", { hasText: "Northstar" })).toBeVisible();
  });

  test("UI-06 admin assigns a task; only the assignee can change its status", async ({ page, browser }) => {
    await login(page, ADMIN);
    await page.goto("/tasks?property=oratoplus");
    await page.getByLabel("Assignee of ORA-001", { exact: true }).selectOption({ label: "Uma User" });
    await page.getByLabel("Priority of ORA-001", { exact: true }).selectOption("P0");
    await page.waitForTimeout(400);

    const other = await browser.newPage();
    await login(other, OTTO);
    await other.goto("/tasks?property=oratoplus");
    await expect(other.getByLabel("Status of ORA-001", { exact: true })).toHaveCount(0);
    await expect(other.getByLabel("Assignee of ORA-001", { exact: true })).toHaveCount(0);
    await other.close();

    const uma = await browser.newPage();
    await login(uma, UMA);
    await expect(uma.getByText("ORA-001")).toBeVisible();          // "My open tasks" on the dashboard
    await uma.goto("/tasks?mine=1");
    await uma.getByLabel("Status of ORA-001", { exact: true }).selectOption("Done");
    await uma.reload();
    await expect(uma.getByLabel("Status of ORA-001", { exact: true })).toHaveValue("Done");
    await uma.close();
  });

  test("UI-07 admin creates and deletes a manual task", async ({ page }) => {
    await login(page, ADMIN);
    await page.goto("/tasks");
    await page.getByRole("button", { name: "New task" }).click();
    const dlg = page.getByRole("dialog", { name: "New task" });
    await dlg.getByLabel("Description", { exact: true }).fill("Book the Toastmasters district partnership call");
    await dlg.getByLabel("Property", { exact: true }).selectOption("oratoplus");
    await dlg.getByRole("button", { name: "Create task" }).click();
    await expect(page.getByText("Created ORA-M001")).toBeVisible();
    await page.getByPlaceholder("Search tasks").fill("Toastmasters district");
    await page.getByRole("button", { name: "Delete ORA-M001" }).click();
    await page.getByRole("dialog", { name: "Delete task?" }).getByRole("button", { name: "Delete" }).click();
    await expect(page.getByText("Deleted ORA-M001")).toBeVisible();
    await expect(page.getByText("No tasks here")).toBeVisible();
  });

  test("UI-08 admin sets a property's ARR target from the dashboard", async ({ page }) => {
    await login(page, ADMIN);
    await page.getByRole("button", { name: "Edit target for OratoPlus" }).click();
    const dlg = page.getByRole("dialog", { name: /Target/ });
    await dlg.getByLabel("ARR target (USD)", { exact: true }).fill("1500000");
    await dlg.getByRole("button", { name: "Save target" }).click();
    await expect(page.getByText("Target updated")).toBeVisible();
    await expect(page.getByText("$1.5M ARR target")).toBeVisible();
  });

  test("UI-09 admin runs the agent, approves a playbook and imports drafts", async ({ page }) => {
    await login(page, ADMIN);
    await page.getByRole("link", { name: "Admin" }).click();
    await expect(page.getByText("not ready")).toBeVisible();         // no local model in the test env
    await expect(page.getByText("off · $0")).toBeVisible();
    await page.getByRole("button", { name: "Vireoka", exact: true }).click();
    await page.getByRole("button", { name: "Start run" }).click();
    await expect(page.getByText(/Started \d{8}-/)).toBeVisible();
    await page.getByRole("button", { name: "Refresh" }).click();
    await page.locator("li > button", { hasText: "1 properties" }).first().click();
    await page.getByRole("button", { name: "View vireoka playbook" }).click();
    await expect(page.getByRole("dialog", { name: /Playbook/ })).toContainText("Design partner");
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText("Approved vireoka")).toBeVisible();
    await page.getByRole("button", { name: "Import to campaigns & partners" }).click();
    await expect(page.getByText(/Imported 2 campaigns, 7 partners, 12 draft emails/)).toBeVisible();
    await page.goto("/campaigns?property=vireoka");
    await expect(page.getByText("vireoka-tier1 (email)")).toBeVisible();
  });

  test("UI-10 admin manages users; a disabled user can't sign in", async ({ page, browser }) => {
    await login(page, ADMIN);
    await page.goto("/admin");
    await page.getByRole("tab", { name: "Users" }).click();
    await page.getByRole("button", { name: "Add user" }).click();
    const dlg = page.getByRole("dialog", { name: "Add user" });
    await dlg.getByLabel("Name", { exact: true }).fill("Priya Partner-Lead");
    await dlg.getByLabel("Email", { exact: true }).fill("priya@vireoka.com");
    await dlg.getByLabel("Temporary password", { exact: true }).fill("priya-temp-pass");
    await dlg.getByRole("button", { name: "Create user" }).click();
    await expect(page.getByText("User created")).toBeVisible();
    const row = page.getByRole("row", { name: /Priya Partner-Lead/ });
    await row.getByText("active").click();
    await expect(row.getByText("disabled")).toBeVisible();

    const p = await browser.newPage();
    await p.goto("/login");
    await p.getByLabel("Email", { exact: true }).fill("priya@vireoka.com");
    await p.getByLabel("Password", { exact: true }).fill("priya-temp-pass");
    await p.getByRole("button", { name: /sign in/i }).click();
    await expect(p.getByRole("alert")).toContainText("wrong email or password");
    await p.close();

    await page.getByRole("tab", { name: "Audit log" }).click();
    await expect(page.getByRole("cell", { name: "user", exact: false }).first()).toBeVisible();
  });

  test("UI-12 admin: recommend Jodibana partners, add a named planner, approve, send, record reply, sign agreement", async ({ page }) => {
    await login(page, ADMIN);
    await page.goto("/partners");
    await page.getByRole("button", { name: "Recommend partners" }).click();
    const dlg = page.getByRole("dialog", { name: "Recommend partners" });
    await dlg.getByLabel("Property", { exact: true }).selectOption("jodibana");
    await dlg.getByRole("button", { name: "Recommend" }).click();
    await expect(dlg.getByText("South Asian wedding planners & coordinators")).toBeVisible();
    await expect(dlg.getByText("Destination wedding resorts & hotels")).toBeVisible();
    await expect(dlg.getByText("Wedding photographers & videographers")).toBeVisible();
    await dlg.getByRole("button", { name: "Show partners" }).click();

    // priority list, highest first
    await expect(page.locator("tbody tr").first()).toContainText("P0");
    await page.getByRole("link", { name: "South Asian wedding planners & coordinators" }).click();
    await expect(page.getByText("Why this partner")).toBeVisible();
    await expect(page.getByText("How to find the right contact")).toBeVisible();
    await page.getByLabel("Business name", { exact: true }).fill("Mandap & Co Planners");
    await page.getByLabel("Contact name", { exact: true }).fill("Priya Nair");
    await page.getByLabel("Contact email", { exact: true }).fill("priya@mandapco.example");
    await page.getByRole("button", { name: "Add named target" }).click();
    await expect(page.getByText(/Added Mandap & Co Planners/)).toBeVisible();
    await page.getByRole("link", { name: "Mandap & Co Planners" }).click();

    // sequence personalised for the named target; admin approves all three
    await expect(page.getByText("Mandap & Co Planners + Jodibana: partnership idea").first()).toBeVisible();
    await page.getByRole("button", { name: /Approve 3/ }).click();
    await expect(page.getByText("Approved 3 emails")).toBeVisible();

    // send from the outreach queue (outbox mode in tests: nothing leaves the machine)
    await page.goto("/outreach?tab=approved&property=jodibana");
    await expect(page.getByText("Outbox mode")).toBeVisible();
    await page.getByRole("button", { name: "Send due now" }).click();
    const rep = page.getByRole("dialog", { name: /1 sent/ });
    await expect(rep).toContainText("Mandap & Co Planners · step 1 → priya@mandapco.example");
    await expect(rep).toContainText("step 2: due");
    await page.keyboard.press("Escape");

    // the partner replies by phone; record it
    await page.goto("/partners?property=jodibana");
    await page.getByRole("link", { name: "Mandap & Co Planners" }).click();
    await expect(page.locator("[aria-current=step]")).toContainText("Contacted");
    await page.getByRole("button", { name: "Record reply" }).click();
    const r = page.getByRole("dialog", { name: "Record a reply" });
    await r.getByLabel("What they said", { exact: true }).fill("Interested - send the referral terms and let's talk Friday.");
    await r.getByRole("button", { name: "Record reply" }).click();
    await expect(page.getByText(/Reply recorded \(positive\) · 2 queued emails stopped/)).toBeVisible();
    await expect(page.locator("[aria-current=step]")).toContainText("In conversation");

    // agreement signed
    await page.getByLabel("Status", { exact: true }).selectOption("signed");
    await page.getByLabel("Key terms / notes", { exact: true }).fill("Two-way referral, 12 months");
    await page.getByRole("button", { name: "Save agreement" }).click();
    await expect(page.getByText("Agreement signed")).toBeVisible();
    await expect(page.locator("[aria-current=step]")).toContainText("Signed");
    await page.goto("/");
    await expect(page.getByText("Agreements signed")).toBeVisible();
    const jb = page.locator("div.rise", { has: page.locator("h3", { hasText: "Jodibana" }) });
    await expect(jb.getByText("signed · 0 in talks")).toBeVisible();
  });

  test("UI-13 general users can draft and record replies but can't approve or send", async ({ page }) => {
    await login(page, UMA);
    await page.goto("/outreach?tab=all");
    await expect(page.getByRole("button", { name: "Send due now" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Check replies" })).toHaveCount(0);
    await page.goto("/partners");
    await expect(page.getByRole("button", { name: "Recommend partners" })).toHaveCount(0);
    await page.getByRole("link", { name: "South Asian wedding planners & coordinators" }).click();
    await page.getByLabel("Business name", { exact: true }).fill("Shaadi Squad Events");
    await page.getByRole("button", { name: "Add named target" }).click();
    await page.getByRole("link", { name: "Shaadi Squad Events" }).click();
    await expect(page.getByRole("button", { name: /Approve/ })).toHaveCount(0);
    await page.getByRole("button", { name: /Shaadi Squad Events \+ Jodibana/ }).first().click();
    const ed = page.getByRole("dialog");
    await expect(ed.getByRole("button", { name: "Approve to send" })).toHaveCount(0);
    await ed.getByLabel("Subject", { exact: true }).fill("Shaadi Squad x Jodibana - families you plan for");
    await ed.getByRole("button", { name: "Save edits" }).click();
    await expect(page.getByText("Saved - needs admin approval")).toBeVisible();
  });

  test("UI-14 email permission: a user marks a partner opted out; an admin emails the approval digest", async ({ page }) => {
    await login(page, UMA);
    await page.goto("/partners?property=jodibana");
    await page.getByRole("link", { name: "Shaadi Squad Events" }).click();
    const consent = page.getByLabel("Email permission", { exact: true });
    await expect(consent).toHaveValue("none");
    await expect(page.getByText(/Cold first touch: sent from your own mailbox/)).toBeVisible();
    await consent.selectOption("opted_out");
    await expect(page.getByText("Opted out - queued emails cancelled")).toBeVisible();
    await expect(page.getByText("cancelled", { exact: true })).toHaveCount(3);
    await page.getByRole("button", { name: "Sign out" }).click();
    await login(page, ADMIN);
    await page.goto("/outreach");
    await page.getByRole("button", { name: "Email approval digest" }).click();
    await expect(page.getByText(/Digest emailed to 1 admin \(outbox\)/)).toBeVisible();
  });

  test("UI-15 admin loads researched partners; a real organisation opens with clickable sources and its drafts", async ({ page }) => {
    await login(page, ADMIN);
    await page.goto("/partners?property=jodibana");
    await page.getByRole("button", { name: "Load researched partners" }).click();
    await expect(page.getByText(/researched partners added/)).toBeVisible();
    await page.getByRole("link", { name: "India Association of Minnesota (IAM)" }).click();
    await expect(page.getByText("researched organisation")).toBeVisible();
    await expect(page.getByRole("link", { name: "iamn.org", exact: true })).toHaveAttribute("href", "https://iamn.org/");
    await expect(page.getByRole("link", { name: "iamn.org/contact" })).toBeVisible();
    await expect(page.getByText("India Association of Minnesota (IAM) + Jodibana: a small pilot idea").first()).toBeVisible();
    await expect(page.getByText("draft", { exact: true })).toHaveCount(3);
  });

  test("UI-16 user builds a LinkedIn campaign: imports connections, adds a partner, sees it counted", async ({ page }) => {
    await login(page, UMA);
    await page.goto("/partners?property=liqmint-institutional");
    await page.getByRole("button", { name: "Import LinkedIn connections" }).click();
    const csv = "Notes:\n\"export notes\"\n\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\n" +
      "Eleni,S.,https://www.linkedin.com/in/eleni-e2e,,Lead,Head of Stablecoins,02 Oct 2026\n";
    await page.locator('input[type="file"]').setInputFiles({ name: "Connections.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
    await page.getByRole("button", { name: "Import", exact: true }).click();
    await expect(page.getByText(/Named contacts you're now connected with: Lead Bank/)).toBeVisible();
    await page.getByRole("button", { name: "Done" }).click();
    await page.goto("/campaigns");
    await page.getByRole("button", { name: "New campaign" }).first().click();
    const dlg = page.getByRole("dialog");
    await dlg.getByLabel("Name").fill("LinkedIn warm intros");
    await dlg.getByLabel("Property").selectOption("liqmint-institutional");
    await dlg.getByRole("button", { name: /create|save/i }).click();
    await expect(page.getByRole("heading", { name: "LinkedIn warm intros" })).toBeVisible();
    await page.getByRole("button", { name: "Add partners" }).first().click();
    await page.getByPlaceholder("Search partners").fill("Lead Bank");
    await page.getByRole("dialog").getByRole("checkbox").first().check();
    await page.getByRole("button", { name: "Add 1" }).click();
    await expect(page.getByRole("link", { name: "Lead Bank" })).toBeVisible();
    await expect(page.getByRole("list", { name: "Campaign funnel" })).toContainText("Partners1");
    await page.getByRole("link", { name: "Lead Bank" }).click();
    await expect(page.getByText("People you know here")).toBeVisible();
    await expect(page.getByText("named contact")).toBeVisible();
    await expect(page.getByRole("link", { name: "LinkedIn warm intros" })).toBeVisible();
    await expect(page.getByText(/Connected on LinkedIn: Eleni S\./)).toBeVisible();
  });

  test("UI-17 admin finds an introduction path from a LinkedIn archive, drafts, approves and sends it", async ({ page }) => {
    await login(page, ADMIN);
    await page.goto("/partners?property=liqmint-institutional");
    await page.getByRole("button", { name: "Import LinkedIn connections" }).click();
    await page.locator('input[type="file"]').setInputFiles(new URL("./fixtures/linkedin_export.zip", import.meta.url).pathname);
    await page.getByRole("button", { name: "Import", exact: true }).click();
    await expect(page.getByText(/warm ties/)).toBeVisible();
    await page.getByRole("button", { name: "Done" }).click();
    await page.goto("/intros");
    await page.getByRole("button", { name: "Find paths" }).first().click();
    await expect(page.getByText(/new paths across/)).toBeVisible();
    const row = page.getByRole("row").filter({ hasText: "Lead Bank" }).filter({ hasText: "Sam Okafor" });
    await expect(row.getByText("insider", { exact: true })).toBeVisible();
    await expect(row.getByRole("link", { name: "Check 2nd-degree" })).toHaveAttribute("href", /network=%5B%22S%22%5D/);
    await row.click();
    await page.getByRole("button", { name: "Draft the ask" }).click();
    await expect(page.getByRole("dialog").getByText(/Note to forward/).first()).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Approve" }).click();
    await page.getByRole("button", { name: "Send approved emails" }).click();
    await expect(page.getByText(/emailed Sam Okafor <sam@lead.example>/)).toBeVisible();
  });

  test("UI-18 admin writes a one-off email to an investor and approves it (outbox mode)", async ({ page }) => {
    await login(page, ADMIN);
    await page.goto("/partners?property=vireoka");
    await page.getByRole("link", { name: "Andrew Brackin", exact: true }).first().click();
    await page.getByRole("button", { name: "Write email" }).click();
    const d = page.getByRole("dialog");
    await expect(d.getByText(/Email isn't connected yet/)).toBeVisible();
    await d.getByLabel("To").fill("andrew@gradient.example");
    await d.getByLabel("Subject").fill("Governance before AI agents move money");
    await d.getByLabel("Message").fill("Hi {{first_name}},\n\nYou named governance for enterprise AI agents as a priority. We are raising a $3M seed. Open to 20 minutes?\n\nNarendra");
    await d.getByRole("button", { name: "Approve & save to outbox" }).click();
    await expect(page.getByText(/Saved to the outbox/)).toBeVisible();
    await expect(page.getByText("one-off email")).toBeVisible();
    await expect(page.getByText(/andrew@gradient.example/).first()).toBeVisible();
  });

  test("UI-19 admin schedules an email for a date, sees it queued, and reschedules in bulk", async ({ page }) => {
    await login(page, ADMIN);
    await page.goto("/partners?property=vireoka");
    await page.getByRole("link", { name: "Andrew Brackin", exact: true }).first().click();
    await page.getByRole("button", { name: "Write email" }).click();
    const d = page.getByRole("dialog");
    await d.getByLabel("Subject").fill("Following up next week");
    await d.getByLabel("Message").fill("Hi {{first_name}},\n\nFollowing up on my note about policy checks for AI agents. Open to 20 minutes?\n\nNarendra");
    await d.getByLabel("When").selectOption("later");
    await d.getByLabel("Send on (your time)").fill("2099-10-09T09:00");
    await expect(d.getByText(/Automatic sending is off/)).toBeVisible();
    await d.getByRole("button", { name: "Approve & schedule" }).click();
    await expect(page.getByText(/Approved - goes Fri, Oct 9/)).toBeVisible();
    await expect(page.getByText(/scheduled Fri, Oct 9/).first()).toBeVisible();
    await page.goto("/outreach?tab=approved");
    const row = page.getByRole("row").filter({ hasText: "Following up next week" });
    await expect(row.getByText(/scheduled Fri, Oct 9/)).toBeVisible();
    await row.getByRole("checkbox").check();
    await page.getByRole("button", { name: /Schedule 1/ }).click();
    await page.getByRole("dialog").getByLabel("Start", { exact: true }).fill("2099-10-10T09:00");
    await page.getByRole("dialog").getByRole("button", { name: "Schedule", exact: true }).click();
    await expect(page.getByText(/Scheduled 1, last Mon, Oct 12/)).toBeVisible();
    await expect(row.getByText(/scheduled Mon, Oct 12/)).toBeVisible();
  });

  test("UI-11 theme toggle and sign-out", async ({ page }) => {
    await login(page, UMA);
    await page.getByRole("button", { name: "Toggle theme" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);
  });
});
