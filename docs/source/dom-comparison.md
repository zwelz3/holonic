# Holonic and the DOM: A Mental Model

Readers familiar with the W3C Document Object Model often recognize structural similarities when they first encounter holonic graphs. The similarities are real and worth making explicit. This page maps the DOM's core concepts onto their holonic counterparts, identifies where the mapping holds cleanly, and flags where the two models diverge.

## Why the DOM is a useful mental model

The DOM has been production infrastructure for nearly three decades. Its event model handles containment, opacity, propagation, and delegation at scale across every browser in existence. Anyone who has written a web application has built intuition about how events bubble up through nested elements, how `event.stopPropagation()` terminates propagation, and how a parent element can react to events fired deep inside a custom component it doesn't understand.

Holonic graphs face an architecturally similar problem. A holarchy is a containment structure: holons can contain other holons (via `cga:memberOf`), parent-child relationships are declared in RDF, and parent holons should not need to introspect their children's interior graphs to know how to route behavior. These are the same constraints the DOM addresses. Borrowing the DOM's vocabulary gives newcomers a fast way to situate holonic ideas against a model they already trust.

That said, the mapping is not exact. The DOM is synchronous; a federated holarchy may be asynchronous. The DOM is a strict tree; a holonic graph allows multiple portal paths. The DOM doesn't validate event payloads against schemas; holons can have SHACL-governed membranes. These differences matter and are covered in the "Where the mapping diverges" section below.

## Concept mapping

The table shows how DOM concepts correspond to the current holonic library. Some correspond directly; some would require additional machinery the library does not currently provide.

| DOM concept | Holonic counterpart | Status |
|-------------|---------------------|-----------------|
| Document | HolonicDataset | Direct correspondence |
| Element | Holon | Direct correspondence |
| Tree (parent-child) | Containment via `cga:memberOf` | Direct correspondence |
| Opaque element interior | Holon interior graphs | Direct correspondence |
| Element attributes | Interior graph triples about the holon IRI | Direct correspondence |
| Shadow DOM boundary | Membrane (SHACL boundary) | Direct correspondence with extension (payload validation) |
| Event target | Destination holon in a traversal | Direct correspondence |
| Event dispatch | `HolonicDataset.traverse()` | Implicit; no explicit `dispatch_event` API |
| Capture phase (parent-first) | Not explicit | Not implemented |
| Target phase | Traversal's final CONSTRUCT + membrane validation | Direct correspondence |
| Bubble phase (child-first) | Not explicit | Not implemented |
| Event handlers | Portal CONSTRUCT queries + SHACL rules | Partial correspondence |
| stopPropagation() | Not explicit | Not implemented |
| preventDefault() | Traversal blocked by membrane validation failure | Implicit correspondence |
| Event object | Not a first-class entity | Implicit; no `cga:Event` type |
| addEventListener | Portal registration | Partial correspondence |
| Custom events | Portal CONSTRUCT with caller-defined query | Direct correspondence |
| Event bubbling terminator | End of path or explicit validation failure | Implicit correspondence |

## What the DOM model suggests about how holons should eventually be dispatched

Cagle's framing (*LinkedIn discussion, April 2026*) proposes that plural-orchestrator coordination can be resolved by treating the holarchy as a DOM-like event propagation structure: events arrive at a holon, propagate through containment, and are consumed, delegated, or ignored. Under that view, dispatching behavior through a holarchy would work roughly as follows.

An **external event source** produces an event directed at a holon. The event source is any `prov:Agent` — a scheduled job, an LLM agent turn, an external HTTP call, a state change somewhere else in the system. The framework does not care who originated the event. It cares only that the event arrived and is targeted at a specific holon.

The event enters the holarchy at a **root or ancestor holon** and begins the **capture phase**: it walks down the containment chain toward the target, giving each ancestor a chance to intercept. An ancestor might log the event, redirect it, transform it, or stop it entirely. If no ancestor intercepts, the event reaches the target.

At the **target phase**, the receiving holon's membrane validates the event payload. If validation passes, the portal's CONSTRUCT query fires and the target's interior is updated. If validation fails, the event is rejected. Either outcome is recorded as a `prov:Activity` in the target's context graph.

The event then enters the **bubble phase**: it propagates back up through the containment chain, giving each ancestor a chance to react to what just happened. An ancestor might aggregate the event into its own metadata (a summary count, a health check), trigger a secondary traversal, or mark its own metadata as dirty. If no ancestor reacts, the event ends its lifecycle.

**Unhandled events** — events that neither capture nor bubble phases react to — are legitimate. They arrived, they were considered, they were not acted on. The framework logs a minimal PROV-O record of the event's lifecycle ("arrived, considered, no handler") to preserve auditability. This is the main extension over the browser DOM, which silently discards unhandled events; a governed holonic system cannot be silent about what it chose not to do.

This model is **not currently implemented**. Portal traversal today is a targeted operation — the caller knows the portal and invokes it directly. There is no capture phase, no bubble phase, no explicit event object, no propagation semantics. Adopting the full DOM-style dispatch model would require new library machinery that is captured as OQ9 in `docs/SPEC.md`.

## Where the mapping diverges

The DOM model maps cleanly for most structural concerns but strains in several places that matter for holonic systems.

### Synchronous vs asynchronous

At first glance, DOM event dispatch looks synchronous: call `element.click()`, and the capture phase, target phase, and bubble phase run in a tight loop before control returns. This is the intuition most engineers carry about the DOM, and it's the intuition that makes the holonic mapping feel uncertain when a federated holarchy enters the picture.

But the DOM is not actually a synchronous system. It is a **synchronous API layered over an asynchronous rendering engine**. The distinction matters because the holonic library faces an architecturally similar split, and naming it explicitly clarifies what a holonic dispatch model would need to preserve versus what it would need to resolve differently.

#### Where the DOM is asynchronous

Several regimes inside the browser operate on their own schedule, decoupled from the synchronous JavaScript call stack that manipulates the DOM:

- **Initial parsing and loading.** As the browser receives HTML over the network, it constructs the DOM tree incrementally while simultaneously fetching scripts, stylesheets, images, and fonts. The DOM exists in a partial state for a non-trivial window before the document is fully loaded. JavaScript running during that window sees a DOM that is actively being built by another process.
- **Rendering and painting.** When JavaScript mutates the DOM, the mutation is synchronous from the script's perspective — the node appears in the tree immediately. But the browser does not repaint on every mutation. It batches mutations, waits for the JavaScript call stack to empty, then runs layout, style recalculation, and paint in a separate pipeline. This is why `element.style.width = '100px'` followed immediately by reading `element.offsetWidth` can force a synchronous layout and why performance-sensitive code avoids that pattern.
- **Async script loading.** `<script async>` and `<script defer>` let scripts download without blocking the parser, then execute when ready — potentially in an order that differs from the document source order. Scripts modifying the DOM under these attributes do so independently of the main parsing flow.
- **Virtual DOM abstractions.** Frameworks like React layer their own scheduling on top of the DOM. A React component's state update is queued, reconciled against a virtual representation, and flushed to the real DOM in a batch. From the component's perspective, the DOM update is asynchronous and non-deterministic in timing — the framework decides when the real DOM catches up.

The pattern across these cases is consistent: the DOM API presents a **synchronous interface** that a script can reason about as if it were an immediate, ordered sequence of operations. The **rendering and persistence machinery** underneath operates on its own schedule, batching, reordering, and deferring work for efficiency.

Event dispatch sits in the synchronous layer — handlers run in a deterministic order relative to each other — but the effects of those handlers (a style change, a node insertion, a scroll position change) hit the asynchronous rendering pipeline. The system works because the boundary is clear: scripts see a synchronous DOM, and the async layer handles the rest.

#### What this suggests for holonic dispatch

The holonic library operates across a spectrum of backends, and the sync/async picture varies with the backend choice.

- **`RdflibBackend`** is in-memory and synchronous. A call to `ds.traverse()` completes before control returns, and the store reflects the change immediately. This is the DOM's synchronous-script analog.
- **`FusekiBackend`** issues HTTP requests against an external server. The call still appears synchronous to the caller (the library waits for the HTTP response), but the actual persistence crosses a network boundary and is subject to server-side batching, indexing, and eventual consistency semantics invisible to the client. This is closer to what happens when a browser script mutates the DOM — the mutation is synchronous to the script, but the downstream effects (repaint, composited layer updates) are not.
- **Federated holarchies** — multiple registries coordinating across backends — are asynchronous end-to-end. An event originating in one registry that needs to propagate to another cannot complete synchronously without blocking the caller on network round-trips, which breaks the composition model.

Given that, a DOM-inspired dispatch API for holonic would likely take the same architectural shape as the DOM: **a synchronous logical model over a potentially asynchronous substrate**. The caller invokes `dispatch_event(target, payload)` and, from their perspective, the capture/target/bubble phases run in order and complete deterministically. Under the hood, the library may:

- Execute all phases synchronously against `RdflibBackend`, matching the DOM's in-document behavior.
- Coalesce multiple HTTP requests to `FusekiBackend` across phases into a smaller number of batched SPARQL updates, similar to how the browser batches DOM mutations before repainting.
- Split dispatch into a synchronous commit (the event is recorded as having arrived, target membrane is validated, portal CONSTRUCT is queued) followed by asynchronous propagation (bubble-phase reactions execute against remote holons when their backends are reachable), with a PROV-O record linking the two.
- Provide an explicit async variant (`async def dispatch_event(...)`) for callers that want to observe completion across remote propagation without blocking.

The critical design principle borrowed from the DOM: **the asynchronous boundary is an implementation concern of the engine, not a concept exposed in the event model.** A script calling `element.click()` does not reason about where in the rendering pipeline its handlers' effects will land. A future holonic caller invoking `dispatch_event` should not have to reason about which backend phase a bubble-phase reaction will complete in — only that the event went through its declared lifecycle and the PROV-O record reflects what happened.

This reframes the sync/async divergence from a reason not to adopt the DOM model into a design problem the DOM has already partially solved. The unresolved questions are federation-specific (cross-registry propagation, partial failure handling, event ordering across independent clocks) and would need their own treatment — but the overall shape of "synchronous logical API, asynchronous substrate" is directly borrowable.

### Tree vs graph

The DOM is a strict tree. Every node has exactly one parent. Event bubbling has an unambiguous path.

A holonic graph is richer. A holon can have multiple containers through different `cga:memberOf` relationships, and portal topology is independent of containment topology. When an event bubbles from a target holon, which "parent" does it bubble to — the containment parent, the portal source, all containment ancestors simultaneously? The DOM does not have to answer this because its topology is constrained; a holonic system must answer it.

The simplest resolution is to restrict event bubbling to the containment graph (`cga:memberOf` chain) while keeping portals as the capture-phase path. But this is a design decision that would need to be made explicit.

### Validation

DOM events carry payloads but those payloads are not validated against schemas. A `click` event is a `click` event; no part of the DOM checks that the payload matches a declared contract.

Holons have SHACL boundaries. If events cross portals in a DOM-style dispatch model, it is natural to ask whether events themselves should be SHACL-validated at each hop. This is an extension the DOM does not have to make but a holonic system might want, because it gives the membrane a role in the event lifecycle: not just "is this target state valid after the event" but "is this event authorized to attempt the transition at all."

### Unhandled events

In the browser, an unhandled event is silent. The DOM neither records that the event arrived nor that nothing handled it. For a UI framework this is the right default — most events are ignored; logging them would drown out the signal.

For a governed holonic system, silence is a problem. Auditability requires that the system be able to answer "did this event arrive, and if so, what happened to it?" for every event that entered the holarchy. This suggests that a DOM-adapted holonic dispatch model should record even unhandled events — as `prov:Activity` records with `cga:eventLifecycle` of "arrived, considered, no handler" or similar. This preserves the lightweight propagation model the DOM offers while meeting the audit requirements of enterprise and defense deployments.

### Shadow DOM and membranes

The DOM's Shadow DOM boundary is the closest DOM concept to a holonic membrane. Shadow DOM creates a scoped subtree whose internals are opaque to the outer document, with selective event retargeting across the shadow boundary. This is almost exactly what a holonic membrane does, with two differences. First, a membrane validates payload structure via SHACL shapes, whereas a shadow boundary only controls visibility. Second, a membrane can reject transitions that cross it; a shadow boundary cannot.

A holonic membrane, under the DOM mapping, is a Shadow DOM boundary with validation teeth.

## What the library provides today

The current library implements several DOM-like concepts natively and leaves others to caller discipline.

**Provided natively:**
- Containment structure via `cga:memberOf` and registry queries
- Opaque interiors (callers can query but the library does not force introspection)
- Membrane validation on governed traversals
- PROV-O records of every traversal, including what happened and why
- Multi-hop path finding that could serve as the capture-phase walk

**Left to caller discipline:**
- Event objects as first-class entities (no `cga:Event` class)
- Explicit capture/target/bubble phases (no phase-indexed dispatch API)
- `stopPropagation()` equivalent (callers manually decide not to continue)
- Bubble-phase reactions (callers would need to explicitly invoke after a traversal)
- Unhandled-event logging (no automatic audit of events that went nowhere)

**Not provided and not captured in the current roadmap:**
- Synchronous dispatch guarantees across backends
- Cross-backend event ordering
- Event payload schemas beyond the existing membrane shapes

## When to think in DOM terms and when not to

The DOM mental model is most useful when you are designing **containment-heavy holarchies** with clear parent-child relationships and you want events to cascade through the structure. Governance hierarchies, organizational structures, nested workflow definitions, and scoped decision authority all fit naturally.

The DOM mental model is **less useful** when you are designing **flat holonic networks** where holons relate to each other as peers through portal topology without meaningful containment. In those cases, "holonet" is a better framing than "holarchy," and DOM's tree-centric event semantics do not translate. The current library works equally well for flat and hierarchical topologies; do not let the DOM analogy constrain you to hierarchical designs.

The DOM mental model is also **less useful** when you are designing systems where events fire continuously against the whole graph rather than being targeted at specific holons. That regime maps more naturally to the graph-level tick framing captured in OQ8 — the Game-of-Life model — rather than to the DOM's targeted dispatch model.

## Related material

- `docs/SPEC.md` OQ8 — Graph-level tick semantics (Cagle's *Graph as State Machine* framing).
- `docs/SPEC.md` OQ9 — DOM-style event propagation as a coordination model.
- Cagle, "What Is a Holon? Part 1: The Graph as State Machine," *The Inference Engineer*, April 2026.
- W3C DOM Level 3 Events specification — for the authoritative treatment of capture/target/bubble phases.
