# Kernel Frontier Discovery Ideas

**User:** Anonymous  
**Created:** 6/25/2026 11:07:08  
**Updated:** 6/26/2026 10:02:44  
**Exported:** 6/26/2026 10:55:53  
**Link:** [https://chatgpt.com/c/6a3d43c3-c408-83e8-a303-35df46d8b88b](https://chatgpt.com/c/6a3d43c3-c408-83e8-a303-35df46d8b88b)  

## Prompt:
6/25/2026, 11:07:07 AM

Look at this project https://github.com/reiniertl/know_kernel I now need to extend it so it can provide "frontier ideas" for new kernel developments/optimizations. For that we want to use the latest papers and interactions in kernel development forums. What are your suggestions?

## Response:
6/25/2026, 11:07:08 AM

I think you have an opportunity to make `know_kernel` substantially more valuable than a simple knowledge base. It can become a **research distillation and frontier discovery engine**.

Those are different problems.

| Capability | Purpose |
|------------|---------|
| Knowledge Base | What do we know? |
| Trend Analysis | What is changing? |
| Frontier Discovery | What should kernel developers investigate next? |
| Opportunity Mining | Where are the unsolved problems? |

The last two are where the real value lies.

---

# I would separate the ontology

Instead of only storing kernel concepts, introduce four layers.

```
Knowledge

Concept
Specification
Subsystem
API
Pattern
Algorithm
Invariant

↓

Evidence

Paper
RFC
LKML discussion
Conference talk
Patchset
Benchmark

↓

Observation

Claim
Problem
Tradeoff
Regression
Optimization
Open question

↓

Opportunity

Research idea
Optimization idea
Refactoring opportunity
Verification opportunity
Missing benchmark
Potential collaboration
```

Notice that **Opportunity** is not something that exists externally.

It is inferred.

---

# Data sources

I would continuously ingest multiple sources.

## Academic

- arXiv
- ACM Digital Library
- IEEE
- USENIX
- OSDI
- SOSP
- ASPLOS
- EuroSys
- ATC

Those are where new mechanisms usually appear first.

---

## Kernel development

Much more important.

- LKML
- linux-next
- subsystem mailing lists
- Patchwork
- Linux Plumbers Conference
- Kernel Summit
- maintainers discussions
- kernel git history
- kernel documentation

These are where actual future directions emerge. ([Indico](https://lpc.events/event/20/abstracts/?utm_source=chatgpt.com))

---

## Community

Less authoritative but useful.

- Reddit kernel community
- LWN articles
- maintainers' blogs
- conference videos

These often explain *why* something happened. ([lwn.net](https://lwn.net/Articles/950567/?utm_source=chatgpt.com))

---

# Do NOT index papers

This is probably the biggest mistake people make.

Instead extract structured knowledge.

Paper

↓

Claims

↓

Evidence

↓

Concepts

↓

Subsystems

↓

Problems

↓

Solutions

↓

Limitations

↓

Future work

Your graph should never care about PDFs.

It should care about ideas.

---

# Frontier score

Every opportunity can receive a score.

```
FrontierScore =
    novelty
  + practical impact
  + implementation maturity
  + maintainer interest
  + number of discussions
  + unresolved objections
  - solved confidence
```

Example

```
Rust abstractions

Novelty          7
Discussion       10
Maintainer buy-in 9
Solved confidence 4

Frontier = 22
```

---

# Mine "Future Work"

Every paper has sections like

```
Limitations

Future Work

Open Questions
```

These should become first-class objects.

```
Paper

↓

Future Work

↓

Problem

↓

Kernel subsystem

↓

Possible approaches
```

Many research ideas originate directly from authors explicitly stating what remains unsolved.

---

# Mine LKML differently

Don't treat emails as documents.

Treat them as debates.

```
Question

↓

Proposal

↓

Objection

↓

Revision

↓

Accepted

↓

Merged
```

That sequence is extremely valuable.

---

You could model

```
Problem

↓

RFC

↓

Review

↓

Alternative

↓

Consensus

↓

Patch

↓

Merge
```

This captures how kernel knowledge evolves rather than just the final outcome.

---

# Mine disagreements

Disagreements are often more valuable than agreements.

Example

```
Developer A

Large folios improve throughput.

↓

Developer B

Memory fragmentation increases.

↓

Developer C

NUMA behaves differently.

↓

Result

Hybrid approach.
```

The disagreement identifies an unresolved design space.

---

# Store rejected ideas

One of the best frontier predictors is

> What has been proposed repeatedly but never accepted?

For example

```
Idea

↓

Rejected

Reason

↓

Rejected

Reason

↓

Rejected

Reason
```

Now ask

```
Has new hardware changed those assumptions?
```

Sometimes the answer becomes "yes."

---

# Mine repeated pain

Suppose over six months you observe

```
DMA mapping

37 discussions

12 bug reports

5 papers

8 benchmark regressions
```

That area deserves attention.

You can compute

```
Pain Score
```

instead of popularity.

---

# Detect converging evidence

This is where graphs become powerful.

Imagine

Paper

```
Lockless queues
```

↓

Conference talk

```
NUMA optimization
```

↓

LKML

```
Scalability issue
```

↓

Benchmark

```
Regression
```

↓

Maintainer

```
Need redesign
```

Those independent sources converge on the same issue.

That is a strong frontier candidate.

---

# Idea synthesis

Instead of asking an LLM

> Give me research ideas

Ask

```
Given

these problems

these rejected solutions

these hardware trends

these benchmarks

these maintainer concerns

produce candidate research directions.
```

That is far more grounded.

---

# Introduce confidence

Every inferred idea should record provenance.

```
Idea

confidence

0.81

Derived from

3 papers

12 LKML discussions

2 rejected RFCs

4 benchmarks
```

This fits naturally with the certainty/provenance model you've already discussed for `know-*` packs.

---

# One feature I think would make `know_kernel` genuinely unique

I would not stop at "frontier ideas."

I would build a **Kernel Research Radar**.

For every subsystem (MM, Scheduler, BPF, io_uring, VFS, Networking, RCU, etc.) maintain a live state such as:

```
Subsystem

Memory Management

Current activity

█████████

Research intensity

██████

Maintainer activity

████████

Open problems

14

Recently solved

5

High-confidence frontier ideas

3

Emerging hardware relevance

High

Risk of regressions

Medium
```

This transforms the system from a passive repository into a continuously updated map of where Linux kernel development is heading. It also aligns with recent work showing that kernel review knowledge and developer discussions can be distilled into reusable validation rules and higher-level insights rather than treated as isolated documents. ([arXiv](https://arxiv.org/abs/2603.24825?utm_source=chatgpt.com))

This is the direction I would pursue. It is significantly more difficult than building a searchable knowledge base, but it is also much harder to replicate because the value comes from the continuously evolving graph of evidence, debates, and inferred opportunities rather than from the raw documents themselves.

---

**Sources:**

- [Linux Plumbers Conference 2026](https://lpc.events/event/20/abstracts/?utm_source=chatgpt.com)
- [Reducing patch postings to linux-kernel](https://lwn.net/Articles/950567/?utm_source=chatgpt.com)
- [Learning From Developers: Towards Reliable Patch Validation at Scale for Linux](https://arxiv.org/abs/2603.24825?utm_source=chatgpt.com)

## Prompt:
6/25/2026, 11:13:02 AM

But how valuable is the current project? I think I may have wasted time. Focus ONLY on this project, the goal here is to assist both human and LLM in deciding what ideas to explore next for kernel development.

## Response:
6/25/2026, 11:13:03 AM

No, I do not think you wasted time.

I do think there is a risk that you are evaluating `know_kernel` against the wrong objective.

If the objective is:

> "Create a knowledge base of kernel concepts."

then the project is not particularly valuable. There are already books, papers, LWN articles, LKML archives, code comments, and increasingly capable LLMs.

A static kernel knowledge graph is useful, but not strategically important.

---

The question you asked is different:

> "Assist humans and LLMs in deciding what ideas to explore next for kernel development."

That objective is much more interesting.

The value then comes from **curation, distillation, and prioritization**, not storage.

# What an LLM lacks today

A frontier model already knows:

- What RCU is.
- What io_uring is.
- How the scheduler works.
- What lock contention means.
- What NUMA means.

Knowledge is not the bottleneck.

The bottleneck is:

> Which problems are worth working on right now?

Even experienced kernel developers struggle with that.

---

# What a human lacks today

Suppose I want to contribute to Linux.

I immediately face:

- Millions of LOC.
- Thousands of maintainers.
- Tens of thousands of LKML threads.
- Hundreds of active patch series.
- Hundreds of papers.

The problem is not information scarcity.

It is information overload.

A newcomer does not know:

- What is already solved.
- What is actively being worked on.
- What is blocked politically.
- What maintainers care about.
- What has already been rejected.

That is where a system like `know_kernel` can create value.

---

# The current project is already solving a hard problem

From what I see, you are building:

```text
Raw Sources
    ↓
Knowledge Extraction
    ↓
Ontology
    ↓
Knowledge Graph
```

Most people stop there.

The graph itself is not the product.

The graph is infrastructure.

Exactly like ext-2 is not the product inside Combobul.

It is the foundation.

---

# Where the real value begins

The moment you can answer questions like:

```text
Which kernel subsystems are seeing increasing research activity?

Which optimization ideas repeatedly appear?

Which ideas were rejected for reasons that may no longer apply?

Which bottlenecks are mentioned by multiple independent sources?

Which papers have not yet influenced kernel discussions?

Which discussions lack benchmark evidence?

Which maintainer concerns remain unresolved?
```

Now the graph becomes useful.

---

# A useful mental model

Think of `know_kernel` as potentially becoming:

```text
GitHub Copilot
        for coding

know_kernel
        for kernel research direction
```

Not:

```text
Wikipedia for kernel concepts
```

Those are very different products.

---

# If I were evaluating the project today

I would rate the current stages like this:

| Stage | Value |
|---------|---------|
| Concept extraction | Medium |
| Ontology construction | Medium |
| Knowledge graph | Medium |
| Research opportunity generation | High |
| Frontier detection | Very high |
| Trend prediction | Extremely high |

The first three are necessary but not sufficient.

The last three are where the differentiation lives.

---

# What worries me

The main risk is not that the project lacks value.

The main risk is that it becomes a very sophisticated storage system.

For example:

```text
Concept
    RCU

Paper
    X

Discussion
    Y

Patch
    Z
```

That is interesting technically.

But nobody pays for that.

Nobody changes their workflow for that.

Nobody gets a paper accepted because of that.

Nobody gets a kernel patch merged because of that.

---

# What would make me excited

Suppose tomorrow the system outputs:

```text
Emerging Opportunity

Subsystem:
    Memory Management

Evidence:

- 7 papers in 18 months
- 12 LKML discussions
- 3 benchmark regressions
- 2 rejected RFCs

Observation:

Large folios improve throughput
but increase fragmentation under NUMA.

Research Gap:

Adaptive folio sizing based on NUMA locality.

Confidence:
    0.82
```

Now I am interested.

Because the system is no longer telling me what Linux is.

It is telling me:

> "Here is where smart people should spend the next six months."

That is a much higher-value capability.

---

# My assessment

Based on your stated goal, I would estimate:

- Current knowledge extraction work: necessary foundation.
- Current standalone value today: moderate.
- Potential value if extended into frontier discovery: very high.

The key observation is that **the ontology and graph are not the product**.

They are your equivalent of ext-0/ext-1/ext-2 in Combobul.

The product is the reasoning layer that sits on top and answers:

> "Given everything we know, what should kernel developers investigate next?"

If that becomes reliable, then the time spent building the knowledge foundation was not wasted. It was the prerequisite for the part that actually creates leverage.

## Prompt:
6/25/2026, 11:18:43 AM

So you mean I still need the current concepts in the system. I need to add more layers so I can record current rends and issues, connect them in the DAG and from that infer high impact areas?

## Response:
6/25/2026, 11:18:44 AM

Yes, but I would go even further.

I think your intuition about ontologies and graphs is causing you to view the current concepts as merely "supporting data." They are actually the anchor that prevents the frontier layer from degenerating into hype tracking.

Consider the difference:

```text
Paper
  ↓
Paper
  ↓
Paper
  ↓
Trend
```

versus

```text
Paper
  ↓
Claim
  ↓
Concept
  ↓
Subsystem
  ↓
Problem
  ↓
Trend
```

The second graph is much more stable.

---

## Think in terms of ontology vs telemetry

Your current project is mostly ontology.

```text
RCU
Scheduler
NUMA
io_uring
BPF
Memory Reclaim
Page Cache
```

These concepts change slowly.

Maybe years.

Maybe decades.

They are the "map."

---

The frontier layer is telemetry.

```text
Discussion volume
Patch volume
Benchmark regressions
Rejected proposals
Open RFCs
Conference papers
Maintainer concerns
```

These change weekly.

They are the "weather."

---

You need both.

A weather system without a map is useless.

A map without weather is static.

---

## I would not add papers directly

Instead I would add new node kinds.

Something like:

```text
Concept
Subsystem
Mechanism
Problem
Solution
Tradeoff

Trend
Observation
Discussion
Proposal
Rejection
Benchmark

Opportunity
```

Notice the difference.

The paper itself is not important.

The extracted observation is.

---

## Example

Today you might have:

```text
Concept
    NUMA

Concept
    Large Folios

Concept
    Memory Reclaim
```

These are timeless.

---

Now imagine a new paper arrives.

Instead of storing:

```text
Paper X
```

you store:

```text
Observation

Large folios improve throughput
on NUMA systems.
```

and connect it:

```text
Large Folios
    ─supports→ Throughput

Large Folios
    ─interacts_with→ NUMA

Observation
    ─observes→ Large Folios
```

Now the paper can disappear and the knowledge remains.

---

## Trends become graph patterns

Suppose six months later:

```text
Observation A
Observation B
Observation C
Observation D
```

all connect to

```text
NUMA
```

and

```text
Large Folios
```

Now you can infer:

```text
Trend

NUMA-aware folio management
```

without anybody explicitly creating the trend node.

The graph topology reveals it.

---

## The key addition is "problems"

I think this is the most important missing layer.

You currently seem to be focused on concepts.

Humans do not work on concepts.

Humans work on problems.

For example:

```text
Concept
    RCU
```

is interesting.

But

```text
Problem
    Grace period latency
```

is actionable.

Likewise:

```text
Concept
    io_uring
```

versus

```text
Problem
    Cross-core synchronization overhead
```

The second one generates work.

---

## Then opportunities become almost automatic

Suppose your graph contains:

```text
Problem
    Grace period latency

Problem
    NUMA scalability

Problem
    Cacheline bouncing
```

and you observe:

```text
15 discussions

4 papers

2 benchmark regressions

3 RFCs
```

all connected to them.

Now an opportunity node can emerge:

```text
Opportunity

NUMA-aware RCU grace period batching
```

with provenance.

---

## This is very similar to ext-2

Notice how close this is to your Combobul thinking.

Current know_kernel:

```text
Facts
    ↓
Concepts
```

What you want:

```text
Facts
    ↓
Concepts
    ↓
Problems
    ↓
Observations
    ↓
Trends
    ↓
Opportunities
```

The concepts are not wasted effort.

They are the equivalent of ext-0/ext-1 facts.

Without them, the higher layers have nothing stable to attach to.

---

## If it were my project

I would not focus next on:

```text
More concepts
```

I would focus on introducing:

```text
Problem
Observation
Proposal
Rejection
Benchmark
Trend
Opportunity
```

Once those exist, the graph can start answering:

> "What kernel problem should I investigate next?"

instead of merely:

> "What is RCU?"

That transition is where the project's value increases dramatically. In fact, I would argue that the current concept graph is probably already sufficient to support a first implementation of the higher layers. You likely do not need 10× more concepts before experimenting with trend and opportunity inference.

## Prompt:
6/25/2026, 11:27:00 AM

So the current know_kernel is the baseline. I need it so the problem, observation, proposal, ... can connect to the knowledge base? But I also need to start including stats, you are posting counts. Then decisions come from something like scoring hot areas. Or areas with the maximal issue overlap, or areas where solving a problem has maximum impact?

## Response:
6/25/2026, 11:27:01 AM

Yes. I think you have now arrived at the actual architecture.

The mistake would be to think:

```text
know_kernel
    +
statistics
    =
frontier engine
```

I don't think that's enough.

What you really need is:

```text
Knowledge Layer
    +
Evidence Layer
    +
Metrics Layer
    +
Inference Layer
```

where the current `know_kernel` is only the first layer.

---

# Layer 1: Knowledge (you already have this)

This is the stable ontology.

```text
RCU
Scheduler
NUMA
Page Cache
MM
BPF
io_uring
VFS
Networking
```

These are your anchor points.

Without them, nothing else has semantic meaning.

---

# Layer 2: Evidence

This is what I think should come next.

```text
Problem
Observation
Proposal
Benchmark
Discussion
Patch
Rejection
```

Examples:

```text
Problem
    Excessive TLB shootdowns

Observation
    NUMA locality affects throughput

Proposal
    Batched shootdowns

Benchmark
    17% improvement on 128 cores
```

These connect directly to the knowledge graph.

```text
Problem
    ─affects→ NUMA

Proposal
    ─addresses→ Problem

Benchmark
    ─supports→ Proposal
```

---

# Layer 3: Metrics

This is where counts enter.

But metrics should not be graph nodes.

They should be attached properties.

For example:

```text
Problem
    Excessive TLB shootdowns

metrics:
    papers = 8
    discussions = 23
    benchmarks = 11
    regressions = 5
    active_patchsets = 3
```

Likewise:

```text
Concept
    NUMA

metrics:
    citations = 217
    active_proposals = 14
    maintainer_mentions = 52
```

---

# Layer 4: Inference

This is where the value emerges.

You start computing scores.

---

## Heat Score

Measures activity.

```text
Heat =
    discussions
  + patchsets
  + papers
  + conference talks
```

High heat means:

> People are actively talking about it.

Not necessarily important.

---

## Pain Score

Measures suffering.

```text
Pain =
    regressions
  + bug reports
  + performance complaints
  + rejected fixes
```

High pain means:

> Users and developers are struggling.

---

## Impact Score

Measures blast radius.

```text
Impact =
    affected subsystems
  + affected workloads
  + affected hardware classes
```

For example:

```text
Page Cache
```

has much larger impact than:

```text
Rare driver bug
```

---

## Opportunity Score

Now it becomes interesting.

```text
Opportunity =
      Pain
    * Impact
    * SolutionConfidence
```

This answers:

> If solved, how much benefit would we get?

---

## Frontier Score

Different from opportunity.

```text
Frontier =
      Novelty
    * EvidenceStrength
    * MaintainerInterest
```

This answers:

> Is this a promising research direction?

---

# The graph becomes a causal structure

The most powerful thing is not counting.

It is topology.

Suppose:

```text
Problem A
Problem B
Problem C
```

all connect to:

```text
Mechanism X
```

Then:

```text
Mechanism X
```

becomes a leverage point.

---

This is very similar to what you already do in Combobul.

Imagine:

```text
Problem
    NUMA imbalance

Problem
    Memory fragmentation

Problem
    Cache locality loss

Problem
    Reclaim inefficiency
```

all connect to:

```text
Large Folios
```

You immediately know:

> Large Folios is a strategic node.

Even before computing scores.

The graph topology tells you.

---

# I would explicitly compute leverage

This is the metric I think is missing from most research systems.

```text
Leverage =
    Number of problems addressed
```

or more generally:

```text
Leverage =
    Σ(problem impact)
```

for all reachable problems.

---

Then the system can answer:

```text
Which unresolved problem affects
the greatest number of other problems?
```

or

```text
Which proposal would eliminate
the largest amount of pain?
```

Those are much more valuable than:

```text
What topic is currently popular?
```

---

# If I were designing v2

I would structure it as:

```text
Knowledge
    Concept
    Mechanism
    Subsystem

Evidence
    Observation
    Problem
    Proposal
    Benchmark
    Rejection

Metrics
    Heat
    Pain
    Impact
    Leverage

Inference
    Trend
    Opportunity
    Frontier
```

The crucial realization is that **the concepts you already built are not the destination**.

They are the coordinate system.

Everything else—problems, proposals, discussions, benchmarks, trends, opportunities—attaches to that coordinate system.

Once that exists, both humans and LLMs can ask:

> "Show me the highest-leverage unsolved problems in memory management."

or

> "Which proposals are most likely to produce outsized impact?"

That is where `know_kernel` transitions from a knowledge repository into a research-navigation system.

## Prompt:
6/25/2026, 11:48:14 AM

So I have ONLY the foundation. That is the graph that connects concepts, and fundamental issues, interactions, invariants, etc. Now If I add the layers you mention I can unlock strategic development directions? Or strategic issue avoidance? Do not repeat what you already said above!

## Response:
6/25/2026, 11:48:15 AM

Yes. But I would frame it slightly differently.

You currently have something analogous to a **domain model** of kernel engineering.

That is already valuable because it provides semantic grounding. However, by itself it cannot answer strategic questions because it has no notion of **time**, **activity**, **pressure**, or **change**.

What the additional layers give you is not merely "more information." They introduce **dynamics**.

---

### Strategic development directions

Once you attach evolving evidence to the graph, you can begin answering questions such as:

- Which subsystem is accumulating unresolved complexity?
- Which mechanism is becoming a bottleneck across multiple independent discussions?
- Which assumptions are being stressed by new hardware?
- Which optimization appears repeatedly under different names?

These are not knowledge queries.

They are emergence queries.

The answer is not explicitly stored anywhere. It emerges from the interaction of many observations attached to the same semantic structure.

---

### Strategic issue avoidance

This may actually be more valuable than finding new opportunities.

Suppose you discover:

```text
Proposal A
    ↓
Touches NUMA

Proposal B
    ↓
Touches NUMA

Proposal C
    ↓
Touches NUMA
```

and

```text
NUMA
    ↓
linked to

Performance regressions
Memory locality issues
Scheduler interactions
```

The system may conclude:

> "Changes in this area historically generate secondary effects in three other subsystems."

That is not a development opportunity.

That is a warning.

The graph becomes capable of identifying **high-risk regions**.

---

### The interesting transition

Today your graph answers:

> What depends on what?

Later it can answer:

> What should we be worried about?

and

> What should we invest effort into?

Those are fundamentally different classes of questions.

---

### Why your current work matters

Imagine trying to build this without the existing graph.

You would end up with:

```text
Paper mentions X
Discussion mentions Y
Benchmark mentions Z
```

but you would not know they all refer to the same underlying mechanism.

The existing knowledge graph performs semantic normalization.

It tells you:

```text
X
Y
Z
```

are all manifestations of

```text
NUMA balancing
```

or

```text
RCU grace period management
```

or

```text
Page cache reclaim
```

Without that normalization, the statistics become noisy counts.

With the normalization, they become evidence.

---

### What I find most interesting

You could eventually identify three different classes of regions:

#### Stable regions

Little activity.

Few regressions.

Few proposals.

Low strategic importance.

---

#### Hot regions

Many proposals.

Many discussions.

Many experiments.

This is where innovation is occurring.

---

#### Fragile regions

Many regressions.

Many reverted patches.

Many rejected proposals.

Strong coupling to other mechanisms.

These are areas where maintainers should be cautious.

---

Notice something important.

The hottest region is not necessarily the most valuable.

The most valuable target is often:

```text
High Impact
+
Moderate Difficulty
+
Low Political Resistance
```

A purely activity-based ranking will miss that.

---

### The connection to your Combobul thinking

This is actually very close to leverage analysis.

In Combobul you care about:

> Which node has the largest blast radius?

Here you care about:

> Which kernel concept has the largest opportunity radius?

or

> Which kernel concept has the largest risk radius?

Those are graph-theoretic questions.

The concepts you already modeled become the topology over which those higher-level analyses operate.

That is why I would view the current `know_kernel` work as infrastructure rather than a dead end. The strategic capabilities only become possible because the semantic structure already exists. Without it, you are left with document search and trend counting. With it, you can begin reasoning about influence, leverage, fragility, and opportunity.



---
Powered by [ChatGPT Exporter](https://www.chatgptexporter.com)