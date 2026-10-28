---
name: create-documentation
description: Write or revise documentation so it reads like clear, professional product documentation, not a machine. Use when creating docs, READMEs, design docs, or any markdown documentation, or when asked to make existing docs read more naturally, clearly, or human.
---

# Creating documentation that sounds human

The goal is simple: a reader should get through the doc without stumbling, and remember what it said. Model the tone, register, and flow on reference documentation like the [AWS EC2 user guide](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/concepts.html): plain, declarative, precisely worded, and organized so a reader always knows where they are. Everything below either describes that model or adds the coherence, simplicity, and clarity a good technical doc needs on top of it.

## The model: define, explain why, then walk through capabilities

Look at how the EC2 guide opens: "Amazon EC2 provides on-demand, scalable computing capacity in the AWS Cloud." One flat sentence, no metaphor, states exactly what the thing is. The next sentence gives the payoff: "Using Amazon EC2 reduces hardware costs so you can develop and deploy applications faster." Then it moves into what the reader can do: "You can use Amazon EC2 to launch as many or as few virtual servers as you need, configure security and networking, and manage storage."

Follow that same shape:

1. **Define the thing in one plain sentence.** No analogy, no scene-setting, just what it is.
2. **State why it matters, immediately after.** One sentence on the payoff or the problem it solves.
3. **Walk through what the reader can do with it**, using direct "you can X to Y" statements, in the order a reader would actually need them.
4. **Define supporting concepts the same way**, one at a time, each in its own short paragraph, building on the last.

## Voice

- Write short, flat, declarative sentences. One idea per sentence. If a sentence has two "and"s or a comma splice joining two separate thoughts, split it.
- Talk to the reader directly with "you" for anything they can do, and "we" only when describing a shared decision or process. Avoid personality flourishes (jokes, dramatic beats, rhetorical asides), the EC2 guide never has them, and a technical or design doc doesn't need them either.
- Use the precise word for the thing, never a generic stand-in. "Build the thing that people use" tells the reader nothing; "produce data in an agreed, open format that's consumable by analytics" tells them exactly what happens, in what shape, and for whom. If you catch yourself writing "thing," "stuff," "handle," "deal with," or "do something with," stop and name the actual noun or verb: the table, the event, the contract, the pipeline, the field, publish, validate, conform, merge.
- Match the register of the domain, not just casual conversation. Plain English isn't the same as casual English. If a doc is about contracts and agreements, say "agreement," "commitment," or "guarantee," not the softer, more casual "promise." Pick the word a reader in that domain would actually use.
- Keep confidence calibrated to the facts. If something is usually true, say "usually." If it's always true, say "always." Don't upgrade a hedge into a certainty, or hedge something that's certain.
- Internal acronyms and tool names (BDE, ASG, EFS, GIP, and the like) get spelled out once, in plain words, on first use, exactly the way EC2 does it ("Amazon Elastic Compute Cloud (Amazon EC2)"), then referred to by the short form for the rest of the doc. Don't switch back and forth between the long form and short form after that first mention.

## Structure the content so it's easy to follow

- Lead with why the reader should care before you explain how something works. State the point in a plain declarative sentence or heading, not a rhetorical question ("Why retries matter" or "This service retries failed writes," not "Why do we need retries?").
- Turn adjacent facts into connected thoughts. If two facts are related by cause, contrast, or sequence, say so ("because," "so," "but," "once") instead of just listing them one after another. A paragraph should read as reasoning, not a stack of facts that happen to sit next to each other.
- Use a glossary-style list, a bolded term followed by a short definition, only when you're enumerating a genuinely parallel set of named things: features, services, options, interfaces. That's exactly how EC2 documents "Features of Amazon EC2" or "Access Amazon EC2." It's the right structure there because each item is a distinct, nameable thing with its own one- or two-sentence definition, not a substitute for explaining a single idea.
- Everywhere else, write prose. If a section is mostly bullets and bold labels standing in for sentences, it's an outline, not a written section, turn it back into paragraphs.
- Use headings only where the topic actually turns, and keep them short, literal noun phrases in sentence case, the way EC2 uses "Pricing for Amazon EC2" or "Access Amazon EC2," not clever or rhetorical headings.
- When a concept is genuinely hard to picture and no plain definition will do, one consistent analogy carried through the whole explanation is fine. Map each real term to its analogy once and reuse that same mapping (don't call the same thing a "box" in one paragraph and a "container" in the next). Reach for this rarely, EC2-style docs mostly don't need it.
- Technical specs, configuration values, and benchmark numbers are data, not prose. Server sizes, instance counts, memory and core counts, or tuning parameters belong in a table or a code block, exactly as given, not rewritten into sentences.
- Point elsewhere instead of digressing. When a related detail lives in another doc, do what EC2 does: "For more information, see [link]," and move on, rather than pulling the tangent into this doc.
- For a decision flow, a multi-step pipeline, or a set of comparable scenarios, add a mermaid diagram right after the prose that describes it. The diagram shows the shape (what connects to what, which branch a decision takes), the prose still carries the reasoning, the diagram doesn't replace it. Keep each diagram scoped to one flow or one scenario rather than one large diagram trying to hold everything.
- If the doc is more than a few sections long, end with a short summary or "Resources" list, not a hollow send-off.

## Words and patterns to avoid

Cut these on sight, they're the tells that make writing feel machine-generated, and none of them appear in well-written reference documentation either:

- Em dashes and en dashes in prose. Use a period, comma, colon, or parentheses instead.
- Filler and throat-clearing: "simply," "just," "in order to" (say "to"), "it is important to note that," "at this point in time" (say "now").
- Puffery and AI-vocabulary: seamless, robust, powerful, effortless, leverage, delve, pivotal, crucial, unlock, harness, foster, elevate, landscape, realm, testament, boasts. State the plain fact instead.
- Decorative connectors: "Additionally," "Furthermore," "Moreover." Use a transition only when the logic actually calls for one.
- Bolted-on lists: "not just X, but Y," "it's not A, it's B," a clipped "no guessing" tacked onto the end of a sentence.
- Generic hype and send-offs: "here's what you need to know," "at its core," "the future looks bright," "let's dive in." End on the last concrete fact, not a send-off.
- Rule-of-three padding. Use as many items as the content actually has, often one or two.

## When revising existing content

- Preserve every fact exactly: numbers, versions, flags, paths, commands, defaults, limits, dates, and units carry over unchanged. When flow and fidelity conflict, fidelity wins.
- Change only how it reads, never what it claims. Don't add a claim the source doesn't make, and don't fill a gap with a plausible-sounding guess, flag genuine ambiguity instead.
- State the current fact, not the history of how you got there. Never narrate the revision itself: no "previously this referenced ADR 12, now replaced by ABC," no "originally assumed to be synthetic data, but it's actually production data," no "this used to be called X." A reader of the doc wasn't there for the earlier draft and doesn't need to be walked through it. Write only what's true now; if the change itself matters to the reader (a migration, a breaking change, a deprecation), record it in a changelog section or release notes, not woven into the main explanation.
- Read it back and fix anything you'd stumble over out loud.

## Before you finish

Check the draft against this list:

- [ ] The doc defines the thing plainly, states why it matters, then walks through capabilities, in that order
- [ ] Every sentence has one idea, a real subject, and a finite verb
- [ ] Every noun and verb is the precise word for the thing, not a generic stand-in ("thing," "stuff," "handle," "deal with")
- [ ] Word choice matches the domain's register (for example, "agreement" or "commitment," not "promise," in a contracts doc)
- [ ] No em dashes, no filler words, no AI-vocabulary from the list above
- [ ] Terminology is consistent (same word for the same thing, every time)
- [ ] Every acronym or internal tool name is spelled out once, on first use
- [ ] Specs, config values, and benchmark numbers are in a table or code block, not dissolved into prose
- [ ] Glossary-style bold-label lists are used only for genuinely parallel named things (features, services, options); everything else is prose
- [ ] Diagrams (if used) are scoped to one flow or scenario each, and match the prose exactly
- [ ] No revision narration ("previously X, now Y," "originally assumed... but actually...") outside a dedicated changelog section
- [ ] The reader could explain the doc's main point back to you after one read
