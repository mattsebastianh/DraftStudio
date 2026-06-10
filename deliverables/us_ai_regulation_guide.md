# The SaaS Founder's Guide to US AI Regulation (Updated June 2026)

*There is no American AI Act. What there is instead — a patchwork of state laws and a federal push to dismantle them — and what you actually have to do about it.*

---

## The one-sentence answer

The United States has no equivalent of the EU AI Act. There is no comprehensive federal AI law, no risk-tier system, and no single rulebook with fixed deadlines. Instead, as of mid-2026, you face two opposing forces: **individual states passing their own AI laws** (several took effect on January 1, 2026), and **a federal government actively trying to override those laws** in the name of a single national framework that doesn't exist yet.

That tension — not any one statute — is the defining feature of US AI regulation right now. Here's how to navigate it.

---

## The federal picture: deregulation, not regulation

While Brussels spent 2024–2026 building a compliance regime, Washington moved the opposite way. Three things matter:

**1. The December 2025 executive order.** On December 11, 2025, the White House signed *"Ensuring a National Policy Framework for Artificial Intelligence."* It doesn't regulate AI companies at all. Instead, it directs the Attorney General to stand up an **AI litigation task force** to challenge state AI laws in court (on preemption and interstate-commerce grounds), and allows federal agencies to **condition discretionary grants** on states refraining from enacting conflicting AI rules.

**2. The March 2026 National Policy Framework.** On March 20, 2026, the administration published its legislative wish list: a light-touch federal standard that would preempt the state patchwork. It's non-binding — a signal of intent, not law.

**3. Proposed legislation that hasn't passed.** The most comprehensive bill to date, the **TRUMP AMERICA AI Act** (Sen. Blackburn), would preempt state law and rewrite AI liability and copyright rules. Like every comprehensive federal AI bill before it, its prospects are uncertain.

**What this means for you:** there is no federal compliance checklist today. Federal exposure comes from *existing* law applied to AI — the FTC on deceptive AI claims ("AI-washing"), the EEOC on discriminatory hiring tools, the SEC on misleading investor statements. The practical rule: don't lie about what your AI does, and don't let it discriminate. Voluntary frameworks like **NIST's AI Risk Management Framework** remain the closest thing to a federal standard, and following one is cheap insurance.

---

## The state picture: where the real obligations live

In the absence of Congress, states wrote their own rules. Four matter most to SaaS companies.

### California — a cluster of transparency laws

California regulates AI through several narrow laws rather than one big act. Most took effect **January 1, 2026**:

- **SB 53 / Frontier AI Transparency Act** — applies only to developers of very large frontier models (training runs above 10²⁶ FLOPS). Unless you're training foundation models, this is your vendor's problem, not yours.
- **AB 2013** — generative AI developers must publish summaries of their training data.
- **SB 243** — companion/conversational chatbots must clearly disclose they're AI.
- **AB 489** — restrictions on AI implying medical credentials in healthcare contexts.
- **SB 942 / AI Transparency Act** — the one to watch. Providers of generative AI tools (image, video, audio) with over one million monthly users must offer AI-content **detection tools** and embed **disclosures in generated content**. Its effective date was pushed to **August 2, 2026** — the same day the EU's transparency rules bite, and very similar in spirit.

### Colorado — the most EU-like law, currently in flux

Colorado's 2024 AI Act was the closest American cousin of the EU AI Act: duties of "reasonable care" for developers and deployers of **high-risk AI** in hiring, lending, housing, insurance, healthcare, education, and government services, with impact assessments and consumer disclosures. Its story since then is a lesson in patchwork volatility: the effective date slipped to **June 30, 2026**, and in May 2026 the state **repealed and replaced it** with **SB 26-189 (Automated Decision-Making Technology Act)**, whose substantive obligations now begin **January 1, 2027**. If your product touches consequential decisions about Colorado residents, put this on your 2026 roadmap.

### Texas — TRAIGA, the light-touch model

The **Texas Responsible AI Governance Act** (effective **January 1, 2026**) bans *intentional* bad uses — AI built or deployed to incite self-harm or crime, unlawfully discriminate, or produce CSAM and certain deepfakes. There's no EU-style risk-management apparatus; if you're not deliberately building something harmful, compliance is largely passive. It also offers a regulatory sandbox and safe harbors for companies following NIST's framework — another reason to adopt it.

### Illinois — AI in hiring

**HB 3773** (effective **January 1, 2026**) amends the state's Human Rights Act to prohibit employers from using AI that discriminates in employment decisions, and requires notice to candidates when AI is used. If your SaaS touches recruiting or HR screening, Illinois joins Colorado on your map.

Beyond these four, Utah requires disclosure when consumers interact with generative AI, New York City's Local Law 144 mandates bias audits for automated hiring tools, and dozens more bills are moving through statehouses. Trackers like multistate.ai count activity in all 50 states.

---

## The wildcard: will any of this survive?

The December 2025 executive order set up a direct collision. The DOJ task force is expected to challenge state laws — California, Colorado, Illinois, and Texas have all been named in commentary — and states have signaled they'll defend them. Courts will decide over the next year or two whether federal preemption arguments hold without an actual federal statute behind them.

**Don't plan around the litigation.** State laws are in force now, enforcement authority sits with state attorneys general now, and a law that might be struck down in 2027 can still cost you in 2026. Comply with what's on the books; treat possible preemption as upside, not strategy.

---

## Your practical checklist

The good news: if you read our EU AI Act guide, you've done most of the thinking already. The same inventory drives both.

**1. Map features to states.** For each AI feature, ask two questions: *does it touch consequential decisions* (hiring, lending, housing, insurance, healthcare)? And *does it generate content or converse with users?* The first bucket triggers Colorado and Illinois; the second triggers California.

**2. Reuse your EU transparency work.** Chatbot disclosure and AI-content labeling built for the EU's August 2, 2026 deadline substantially covers California's SB 243 and SB 942 — which lands the same day. Build once, comply twice.

**3. If you're in the high-risk bucket, start the Colorado workstream.** Impact assessments, consumer notices, and discrimination testing under the replacement law begin January 1, 2027 — conveniently before the EU's December 2027 high-risk deadline, so Colorado becomes your dress rehearsal.

**4. Adopt NIST AI RMF as your spine.** It's voluntary, it's free, it earns safe-harbor treatment in Texas, and it's the most likely template for any future federal standard.

**5. Watch your marketing.** The most active US enforcer today is the FTC, and its theory is simple: claiming your AI does things it doesn't is deception. Have someone review every "AI-powered" claim on your site.

**6. Assign an owner and a tracker.** The US landscape changes monthly. One person, one quarterly review of the states where you have users.

---

## The bottom line

Europe gives you one demanding rulebook; America gives you fifty potential ones and a federal government suing to erase them. For a typical SaaS company the practical burden is smaller than the EU's — transparency disclosures, honest marketing, and bias diligence on any hiring or lending features — but the uncertainty is larger. The winning move is the same on both continents: inventory your AI, be transparent about it, document your risk thinking once against NIST, and let that single foundation absorb whichever rulebook survives.

*This guide is for general information and isn't legal advice. State applicability turns on facts — user counts, decision types, where your users live — so consult counsel for anything in the high-risk bucket.*

---

### Sources

- [White & Case — AI Watch: Global regulatory tracker, United States](https://www.whitecase.com/insight-our-thinking/ai-watch-global-regulatory-tracker-united-states)
- [King & Spalding — New State AI Laws Effective January 1, 2026, But a New Executive Order Signals Disruption](https://www.kslaw.com/news-and-insights/new-state-ai-laws-are-effective-on-january-1-2026-but-a-new-executive-order-signals-disruption)
- [Ropes & Gray — White House Legislative Recommendations: National Policy Framework for AI and Federal Preemption of State AI Laws](https://www.ropesgray.com/en/insights/alerts/2026/03/the-white-house-legislative-recommendations-national-policy-framework-for-artificial-intelligence-an)
- [Jones Walker — The TRUMP AMERICA AI Act: Federal Preemption Meets Comprehensive Regulation](https://www.joneswalker.com/en/insights/blogs/ai-law-blog/the-trump-america-ai-act-federal-preemption-meets-comprehensive-regulation.html?id=102lzdi)
- [Cooley — State AI Laws: Where Are They Now? (April 2026)](https://www.cooley.com/news/insight/2026/2026-04-24-state-ai-laws-where-are-they-now)
- [Baker Botts — U.S. AI Law Update (January 2026)](https://www.bakerbotts.com/thought-leadership/publications/2026/january/us-ai-law-update)
- [MultiState — State AI Legislation Tracker](https://www.multistate.ai/artificial-intelligence-ai-legislation)
