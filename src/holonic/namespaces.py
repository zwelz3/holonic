"""Namespace definitions used throughout the holonic library."""

from rdflib import Namespace

CGA  = Namespace("urn:cga:")
PROV = Namespace("http://www.w3.org/ns/prov#")

# Standard prefix block for embedding in TTL strings.
# Import this and prepend to any TTL snippet.
TTL_PREFIXES = """\
@prefix cga:   <urn:cga:> .
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix skos:  <http://www.w3.org/2004/02/skos/core#> .
@prefix dct:   <http://purl.org/dc/terms/> .
@prefix prov:  <http://www.w3.org/ns/prov#> .
"""
