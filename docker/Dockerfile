# DRC/ERC runner: pinned KiCad image + our summary script.
# Build from repo root: docker build --build-arg KICAD_TAG=9.0 -f docker/Dockerfile -t kal-drc:9.0 .
ARG KICAD_TAG=9.0
FROM kicad/kicad:${KICAD_TAG}

COPY orchestrator/drc_summary.py /opt/kal/drc_summary.py
COPY docker/drc.sh /opt/kal/drc.sh

WORKDIR /work
ENTRYPOINT ["bash", "/opt/kal/drc.sh"]
