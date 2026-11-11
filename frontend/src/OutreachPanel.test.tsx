import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import OutreachPanel from "./OutreachPanel";
import type { OutreachPlan } from "./types";

const PLAN: OutreachPlan = { status: "ready", notes: "Public sources checked.", checked_at: "2026-11-10T12:00:00Z", contacts: [{
  name: "Casey Smith", company: "Acme", role: "Engineering Manager", relevance: "Leads the platform team.",
  source_url: "https://acme.example/team", evidence_quote: "Casey Smith leads Acme's platform team.",
  email: "casey@acme.example", email_source_url: "https://acme.example/team", linkedin_url: "https://www.linkedin.com/in/casey-smith",
  email_subject: "A question about your platform team", email_body: "Hi Casey, what does your team most value in a new engineer?",
  linkedin_message: "Hi Casey, I am exploring Acme's backend role. Could I ask about your team?",
}] };

it("shows evidenced email first and copies an unsent draft", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  render(<OutreachPanel plan={PLAN} />);
  expect(screen.getByText("casey@acme.example")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Employment source" })).toHaveAttribute("href", PLAN.contacts[0].source_url);
  fireEvent.click(screen.getByRole("button", { name: "Copy email draft for Casey Smith" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining("To: casey@acme.example\nSubject:")));
  expect(screen.getByText(/No email, LinkedIn message, or connection request has been sent/)).toBeInTheDocument();
});

it("offers LinkedIn when no published email was found", () => {
  render(<OutreachPanel plan={{ ...PLAN, contacts: [{ ...PLAN.contacts[0], email: null, email_source_url: null }] }} />);
  expect(screen.getByText(/No published work email confirmed/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Copy email/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Copy LinkedIn/ })).toBeInTheDocument();
});

it("explains unavailable research while keeping the result view usable", () => {
  render(<OutreachPanel plan={{ status: "unavailable", notes: "Search unavailable. Your resume is ready.", checked_at: "", contacts: [] }} />);
  expect(screen.getByText("Search unavailable. Your resume is ready.")).toBeInTheDocument();
});
