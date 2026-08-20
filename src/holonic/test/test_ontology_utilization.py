"""Every term the CGA ontology declares is accounted for.

An ontology accretes. A term gets added for a design that is later dropped, or
renamed with the old spelling left behind, and nothing notices -- the file still
parses, the shapes still validate, and the dead term sits there being quietly
authoritative. Six months on nobody can tell which half of the vocabulary is
real.

This module makes that impossible to do silently. Every ``cga:`` term is either
**live** -- demonstrably used -- or **declarative**, listed below with a reason.
A term that is neither fails the audit, and so does a registry entry for a term
that has since become live or been deleted. Adding vocabulary stays easy;
adding it *without saying why* does not.

Liveness is established three ways, because no single one is sufficient:

1. **Static** -- the term appears in library source. Misses anything built by
   interpolation.
2. **Runtime** -- the term reaches the graph when a representative holarchy is
   exercised. This is what catches dynamic construction: membrane health is
   emitted as ``f"urn:holonic:ontology:{health.value.capitalize()}"``, so
   ``cga:Intact`` appears in no source file and is entirely live.
3. **Constrained** -- the term is referenced by ``cga-shapes.ttl``. A term the
   library never writes but SHACL checks when a *user* writes it is doing work.

"Unused by the library" is not the same as dead. The library is one consumer of
this vocabulary, not its only intended one. ``cga:derivedFrom`` is the clearest
case: R5.3 requires it to exist precisely so that structural dependency has a
term of its own and nobody overloads ``prov:wasDerivedFrom``. A reserved term is
*supposed* to be unused here. Deleting it would breach the requirement it
satisfies.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from rdflib import OWL, RDF, RDFS, SKOS, Graph

from holonic import HolonicDataset, MembraneHealth, RdflibBackend

CGA = "urn:holonic:ontology:"
ONTOLOGY_DIR = Path(__file__).parent.parent / "ontology"
SRC_DIR = Path(__file__).parent.parent

DECLARED_TYPES = (
    OWL.Class,
    OWL.ObjectProperty,
    OWL.DatatypeProperty,
    OWL.AnnotationProperty,
    RDFS.Class,
)

# ---------------------------------------------------------------------------
# Declarative vocabulary: declared for consumers, deliberately not used here.
#
# Each entry needs a reason, and the reason should say who the term is *for*.
# "Not used yet" is not a reason -- that is the state this audit exists to
# surface. If a term is speculative, say so; that is an honest entry and it
# gives a reviewer something to argue with.
# ---------------------------------------------------------------------------

DECLARATIVE: dict[str, str] = {}


def _register(reason: str, *terms: str) -> None:
    for term in terms:
        DECLARATIVE[term] = reason


_register(
    "Enumeration container, or a member of one the library never emits. The "
    "container class is only ever a type, never an object. cga:Intact, "
    "Weakened and Compromised are deliberately absent from this list -- the "
    "runtime probe emits all three, so they are live.",
    "MembraneHealth", "HolonStatus", "Active", "Proposed", "PortalType",
)

_register(
    "Holon taxonomy offered to consumers. `add_holon(holon_type=...)` accepts "
    "any of these; which one a deployment uses is its modelling decision, not "
    "the library's. PersistentHolon is live only because the runtime probe "
    "happens to pass it.",
    "EphemeralHolon", "GovernanceHolon", "IndexHolon",
)

_register(
    "Security and handling markings applied by consumers to their own data. "
    "The library never classifies anything -- doing so would require it to "
    "understand payloads it deliberately treats as opaque.",
    "CUI", "PII", "Public", "Internal", "Restricted", "Secret", "TopSecret",
)

_register(
    "Governance vocabulary. OQ10 identifies this cluster as the part of the "
    "ontology that maps cleanly onto established upper ontologies (CCO Agent, "
    "gist Organization) and is intended for downstream enterprise modelling. "
    "It describes an organisation's data estate, which the library has no "
    "view of.",
    "dataOwner", "domainSteward", "domainPolicy", "containsType",
    "sourceOfTruthFor", "repositoryOfTruthFor", "backedBySystem",
    "consumedByProcess", "governedByProcess", "producedByProcess",
    "providesCapability", "processStage", "systemEndpoint", "gateCondition",
)

_register(
    "Reserved by requirement rather than used. R5.3 requires cga:derivedFrom "
    "to exist and to stay distinct from prov:wasDerivedFrom, so that "
    "persistent holon-to-holon structural dependency has a term of its own. "
    "Its being unused by the library is the point; see "
    "TestDerivationVocabulary.",
    "derivedFrom",
)

_register(
    "Declared for a capability that is modelled but not implemented. A "
    "consumer can record these today and the shapes will check them, but no "
    "library call produces them. Candidates for removal if no consumer "
    "materialises -- tracked as a group so the decision is made once rather "
    "than term by term.",
    "adjacentTo", "exposesPortal", "isTraversable",
    "activationEvent", "holonDepth", "splitTarget", "splitCriteria",
    "sourceRealizes", "targetRealizes", "usesAlignment",
    "BidirectionalPortal", "UnidirectionalPortal", "portalType",
)

_register(
    "Domain or range in another term's declaration. It is structural: removing "
    "it would leave dangling references in the ontology even though nothing "
    "instantiates it directly.",
    "LayerGraph",
)


# ---------------------------------------------------------------------------
# Liveness detection
# ---------------------------------------------------------------------------


def _declared_terms() -> set[str]:
    """Every local name cga.ttl declares as a class, property, or individual."""
    graph = Graph().parse(ONTOLOGY_DIR / "cga.ttl", format="turtle")
    terms = set()
    for subject, _, obj in graph.triples((None, RDF.type, None)):
        if not str(subject).startswith(CGA):
            continue
        if obj in DECLARED_TYPES or str(obj).startswith(CGA):
            terms.add(str(subject)[len(CGA):])
    return terms


def _mentions(term: str, blob: str) -> bool:
    """Does ``blob`` reference ``cga:term`` or its full IRI?

    The trailing guard stops ``cga:count`` matching ``cga:countOf``; without it
    a deleted term stays "live" because a longer one starts with its name.
    """
    return re.search(rf"(cga:|{re.escape(CGA)}){re.escape(term)}(?![A-Za-z0-9_])", blob) is not None


def _library_sources() -> list[Path]:
    """Library ``.py`` files, excluding the test package and bytecode caches.

    Excluding tests is what makes the audit mean anything: a term is live
    because the *library* uses it, not because a test asserts it exists. The
    six verification tests added for R1.4/R5.2/R5.3/R5.4/R9.2/R9.44 name CGA
    terms directly, so including them would report those terms live on the
    strength of the test that checks they are declared -- circular, and it
    would quietly hide exactly the dead vocabulary this module hunts.

    Matched on path *components* rather than a substring. ``"/test/" not in
    str(p)`` is never true on Windows, where the separator is a backslash, so
    the whole test package was scanned as library source and three terms
    (``LayerGraph``, ``Public``, ``derivedFrom``) were reported live there and
    declarative on Linux. Guarded by ``test_static_scan_excludes_tests``.
    """
    sources = []
    for path in SRC_DIR.rglob("*.py"):
        parts = path.relative_to(SRC_DIR).parts
        if "__pycache__" in parts or parts[0] == "test":
            continue
        sources.append(path)
    return sources


def _static_live() -> set[str]:
    """Terms named literally in library source, excluding tests and ontology."""
    blob = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in _library_sources()
    )
    return {t for t in _declared_terms() if _mentions(t, blob)}


def _constrained() -> set[str]:
    """Terms the SHACL shapes reference, so a user writing them gets checked."""
    blob = (ONTOLOGY_DIR / "cga-shapes.ttl").read_text(encoding="utf-8")
    return {t for t in _declared_terms() if _mentions(t, blob)}


def _runtime_live() -> set[str]:
    """Terms that reach the graph when a representative holarchy is exercised.

    Deliberately broad rather than minimal: the point is to touch every write
    path the library has, so that a term emitted only by an uncommon one still
    registers. The ontology graphs themselves are excluded -- every term
    appears there by definition, which would make the whole audit vacuous.
    """
    ds = HolonicDataset(RdflibBackend())
    ds.add_holon("urn:h:a", "A", holon_type="cga:PersistentHolon")
    ds.add_holon("urn:h:b", "B", member_of="urn:h:a")
    ds.add_interior("urn:h:a", "<urn:i:1> a <urn:ex:Item> .")
    ds.add_boundary(
        "urn:h:a", "<urn:s:S> a sh:NodeShape ; sh:targetClass <urn:ex:Item> ."
    )
    ds.add_portal(
        "urn:p:ab",
        source_iri="urn:h:a",
        target_iri="urn:h:b",
        portal_type="cga:TransformPortal",
        construct_query=(
            "CONSTRUCT { ?s a <urn:ex:C> } "
            "WHERE { GRAPH <urn:h:a/interior> { ?s a <urn:ex:Item> } }"
        ),
    )
    ds.validate_membrane("urn:h:a")
    ds.traverse("urn:h:a", "urn:h:b", validate=True, agent_iri="urn:agent:x")
    for health in MembraneHealth:
        ds.record_validation(holon_iri="urn:h:a", health=health, agent_iri="urn:agent:x")
    ds.refresh_all_metadata()

    live = set()
    for graph_iri in ds.backend.list_named_graphs():
        if graph_iri.startswith(CGA):
            continue
        for triple in ds.backend.get_graph(graph_iri):
            for node in triple:
                text = str(node)
                if text.startswith(CGA):
                    live.add(text[len(CGA):])
    return live


@pytest.fixture(scope="module")
def audit():
    declared = _declared_terms()
    live = _static_live() | _constrained() | _runtime_live()
    return declared, live & declared


class TestOntologyUtilization:
    def test_ontology_declares_terms(self, audit):
        """Guard: an empty declaration set would make every other test vacuous."""
        declared, _ = audit
        assert len(declared) > 50, f"only {len(declared)} terms parsed from cga.ttl"

    def test_static_scan_excludes_tests(self):
        """The static pass must not read the test package.

        This failed silently on Windows: the exclusion matched the substring
        ``"/test/"``, which never appears in a path built with backslashes, so
        every test file was scanned as library source. The audit still passed
        on Linux and reported three terms live on Windows that are only ever
        named by tests -- a platform-dependent answer to "is this vocabulary
        used", which is worse than an outright failure.

        Asserted on the file list rather than on the outcome, because the
        outcome is only wrong for terms that happen to be test-mentioned.
        """
        offenders = [
            str(p.relative_to(SRC_DIR))
            for p in _library_sources()
            if "test" in p.relative_to(SRC_DIR).parts
        ]
        assert not offenders, (
            f"the static liveness scan is reading test files, so terms will be "
            f"reported live because a test names them: {offenders[:5]}"
        )
        assert _library_sources(), "the static scan found no library sources at all"

    def test_every_declared_term_is_live_or_registered(self, audit):
        """No dead fluff: a term is used, or it says why it is not."""
        declared, live = audit
        unaccounted = sorted(declared - live - set(DECLARATIVE))
        assert not unaccounted, (
            f"{len(unaccounted)} CGA term(s) are neither used by the library, "
            f"constrained by cga-shapes.ttl, emitted at runtime, nor listed in "
            f"DECLARATIVE with a reason: {unaccounted}. Either wire the term up, "
            f"delete it, or register it and say who it is for."
        )

    def test_registry_has_no_stale_entries(self, audit):
        """A term that became live must leave the registry.

        Without this the registry rots in the other direction: entries claiming
        a term is declarative long after the library started emitting it, which
        is exactly the stale documentation this audit exists to prevent.
        """
        _, live = audit
        stale = sorted(set(DECLARATIVE) & live)
        assert not stale, (
            f"{len(stale)} term(s) are registered as declarative but are now "
            f"live: {stale}. Remove them from DECLARATIVE."
        )

    def test_registry_has_no_phantom_entries(self, audit):
        """A registry entry for a term cga.ttl no longer declares is a leftover."""
        declared, _ = audit
        phantom = sorted(set(DECLARATIVE) - declared)
        assert not phantom, (
            f"DECLARATIVE names {len(phantom)} term(s) that cga.ttl does not "
            f"declare: {phantom}. They were probably renamed or removed."
        )

    def test_every_registry_entry_carries_a_reason(self):
        """A blank reason is an unreviewed entry wearing a reviewed one's clothes."""
        thin = sorted(t for t, why in DECLARATIVE.items() if len(why.strip()) < 40)
        assert not thin, f"registry entries with no substantive reason: {thin}"

    def test_declarative_share_is_bounded(self, audit):
        """More than half the vocabulary being unused is a design smell.

        Not a correctness property -- a ratio, deliberately loose, that turns
        gradual accretion into a visible event. If this fires, the question is
        whether the ontology has grown past what anyone uses, and the answer
        may legitimately be "no, raise the bound" -- but it should be answered.
        """
        declared, live = audit
        ratio = len(live) / len(declared)
        assert ratio >= 0.55, (
            f"only {len(live)}/{len(declared)} ({ratio:.0%}) of CGA terms are "
            f"live; {len(DECLARATIVE)} are registered as declarative. Review "
            f"whether the vocabulary has outgrown its use."
        )


class TestOntologyHygiene:
    """Structural checks that catch the other ways an ontology rots."""

    def test_every_term_is_documented(self):
        """A term with no human-readable description cannot be used by anyone else.

        The audit above asks whether a term is *used*; this asks whether it
        could be. An undocumented term in a vocabulary offered to consumers is
        dead in a second sense -- present, but unusable by anyone who did not
        write it.
        """
        graph = Graph().parse(ONTOLOGY_DIR / "cga.ttl", format="turtle")
        describes = (SKOS.definition, RDFS.label, RDFS.comment)
        undocumented = [
            str(subject)[len(CGA):]
            for subject, _, obj in graph.triples((None, RDF.type, None))
            if str(subject).startswith(CGA)
            and obj in DECLARED_TYPES
            and not any(graph.value(subject, p) for p in describes)
        ]
        assert not undocumented, (
            f"{len(undocumented)} CGA term(s) carry no skos:definition, "
            f"rdfs:label or rdfs:comment: {sorted(set(undocumented))}"
        )

    def test_no_term_is_declared_twice_with_different_types(self):
        """A term typed as both a class and a property is a copy-paste artifact."""
        graph = Graph().parse(ONTOLOGY_DIR / "cga.ttl", format="turtle")
        conflicted = []
        for subject in set(graph.subjects(RDF.type, None)):
            if not str(subject).startswith(CGA):
                continue
            types = {t for t in graph.objects(subject, RDF.type) if t in DECLARED_TYPES}
            if len(types) > 1:
                conflicted.append((str(subject)[len(CGA):], sorted(str(t) for t in types)))
        assert not conflicted, f"terms with conflicting declarations: {conflicted}"
