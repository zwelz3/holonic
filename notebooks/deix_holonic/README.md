# DEIX Ontology × Holonic RDF: Use Cases (Revised)

Jupyter notebooks demonstrating how the INCOSE DEIX Ontology aligns with the holonic four-graph model, using **actual named-graph hyperedges** and the **full translation pipeline** through DEIX as the canonical intermediate.

## What Changed From the First Attempt

The first attempt had two problems:

1. It used flat graphs with DEIX class names rather than actual named graphs referencing each other as hyperedges.
2. It never showed the translation pipeline where DEIX serves as the canonical hub between tools with different local ontologies.

This revision fixes both. The named graph IRIs (interior, boundary, projection, context) appear as subjects and objects in each other's triples — that IS the hypergraph. And the pipeline demonstrates real vocabulary translation: `sysml:` → `deix:` → `sim:`, with SHACL validation and PROV-O provenance at every boundary crossing.

## The Core Architecture

```
ToolX Interior    ToolX      ToolX-to-DEIX   DEIX         DEIX-to-ToolY   ToolY      ToolY Interior
(local vocab)   → Surface  → Portal        → Interior   → Portal       → Surface  → (local vocab)
                  (SHACL)    (CONSTRUCT)     (deix: vocab) (CONSTRUCT)    (SHACL)
```

Each tool keeps its own vocabulary in its own interior. DEIX is the canonical hub. Portals carry SPARQL CONSTRUCT queries that translate between local and canonical vocabularies. The Digital Thread is the ROLE applied to the collection of portal traversals and their provenance chains.

## The Three Notebooks

### 01 — Hypergraph Foundations

Establishes the pattern: named graph IRIs appearing as subjects/objects in other named graphs. Shows how a SysML holon's context graph references its own interior graph IRI as a `prov:Entity`, the DEIX holon's interior graph IRI as a `prov:wasDerivedFrom` target, and portal IRIs from the boundary graph.

**Key demonstration:** The context graph contains triples ABOUT other named graphs. This is the hyperedge pattern — a named graph is both a container (holding triples) and a participant (referenced by URI in other graphs).

### 02 — Full Translation Pipeline: ToolX → DEIX → ToolY

Builds three holons with three different vocabularies:
- SysML interior uses `sysml:Block`, `sysml:ValueProperty` (local to Cameo/Capella)
- DEIX interior uses `deix:Digital_Artifact`, `deix:Digital_Information` (canonical)
- Sim interior uses `sim:InputBlock`, `sim:InputParam` (local to AFSIM)

Demonstrates the complete flow:
1. Discover the DEIX surface (query its SHACL shapes)
2. Build the SysML→DEIX portal (CONSTRUCT: `sysml:Block` → `deix:Digital_Artifact`)
3. Traverse the portal (execute CONSTRUCT against SysML interior)
4. Load projected triples into DEIX interior
5. Build the DEIX→Sim portal (CONSTRUCT: `deix:Digital_Artifact` → `sim:InputBlock`)
6. Traverse the portal (execute CONSTRUCT against DEIX interior)
7. Load projected triples into Sim interior
8. Validate against Sim boundary (SHACL)
9. Record PROV-O provenance at every step

**Key demonstration:** The same data (mass = 142.3 kg) traverses three vocabularies. At each portal crossing, the CONSTRUCT reshapes the triples and SHACL validates the output. The provenance chain records which graph generated which.

### 03 — Digital Thread as a Role on the Portal Network

Shows that the Digital Thread is NOT a separate graph of trace links. It IS the **ROLE** applied to the collection of portal traversals and their provenance activities.

Per DEIX:
- `deix:Digital_Thread_Role` is realized in `deix:Act_of_Measuring_Consistency`
- Each portal traversal + validation IS an Act of Measuring Consistency
- The `Thread_Description_ICE` is composed of these measurements
- The `prov:wasDerivedFrom` chain across interior graph IRIs IS the thread structure

**Key demonstration:** After executing the pipeline, query the merged context graphs. The derivation chain (`graph A prov:wasDerivedFrom graph B`) emerges automatically from the portal traversals. Apply the DEIX `Digital_Thread_Role` to this chain. No separate thread maintenance required.

## Where the Hyperedges Are

The named-graph-as-participant pattern appears in four places:

| Context graph contains | Subject/Object is | This creates |
|---|---|---|
| `<.../interior> prov:wasGeneratedBy <activity>` | Interior graph IRI | Interior → Context hyperedge |
| `<activity> prov:used <.../interior>` | Source interior IRI | Source → Target hyperedge |
| `<.../interior> prov:wasDerivedFrom <.../interior>` | Two interior IRIs | Cross-holon hyperedge |
| `<activity> cga:viaPortal <portal>` | Portal IRI from boundary | Context → Boundary hyperedge |

Every one of these triples sits IN one named graph but references ANOTHER named graph's IRI. The graph IRI is the hyperedge connecting the layers.

## Running

```bash
# Requires the holonic library on the path
pip install rdflib pyshacl

python 01_hypergraph_foundations.py
python 02_tool_to_deix_pipeline.py
python 03_digital_thread_as_role.py

# As Jupyter notebooks
pip install jupytext
jupytext --to notebook *.py
jupyter lab
```

## DEIX Ontology Classes Referenced

All from `https://semantic.incose.org/DEIX_Ontology#`:

| Class | Notebook | Role in Pipeline |
|---|---|---|
| `Digital_Artifact` | 02, 03 | Canonical class in DEIX interior |
| `Digital_Information` | 02 | Parameter values in DEIX form |
| `Digital_Twin` | 01 | Full four-layer holon |
| `Digital_Twin_Role` | 01 | Realized in Synchronization_Process |
| `Authoritative_Source_of_Truth_Role` | 01 | Assigned by Authority in context |
| `Authority` | 01 | prov:Agent with governance rights |
| `Act_of_Role_Assignment` | 01 | prov:Activity for role assignment |
| `Thread_Description_ICE` | 03 | Composed of traversal activities |
| `Digital_Thread_Role` | 03 | Realized in consistency measurements |
| `Act_of_Measuring_Consistency` | 03 | Portal traversal + validation |
| `Synchronization_Process` | 01 | Boundary constraint for twins |
| `Digital_System_View` | 01 | Projection for stakeholders |
| `Concern_Expression` | 01 | Why a projection exists |
