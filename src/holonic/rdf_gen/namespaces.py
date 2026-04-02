"""Namespace definitions for rdf_gen."""

from rdflib import Namespace

GEN = Namespace("urn:gen:")
ENG = Namespace("urn:eng:")
SIM = Namespace("urn:sim:")

TTL_PREFIXES = """\
@prefix gen:   <urn:gen:> .
@prefix eng:   <urn:eng:> .
@prefix sim:   <urn:sim:> .
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix dct:   <http://purl.org/dc/terms/> .
@prefix prov:  <http://www.w3.org/ns/prov#> .
"""

SPARQL_PREFIXES = """
PREFIX gen:   <urn:gen:>
PREFIX eng:   <urn:eng:>
PREFIX sim:   <urn:sim:>
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:   <http://www.w3.org/2002/07/owl#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>
PREFIX sh:    <http://www.w3.org/ns/shacl#>
PREFIX dct:   <http://purl.org/dc/terms/>
PREFIX prov:  <http://www.w3.org/ns/prov#>
"""
