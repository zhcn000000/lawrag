FROM postgres:18-trixie

RUN rm -f /etc/apt/sources.list.d/pgdg.list /etc/apt/sources.list.d/pigsty.list
COPY ./docker/database/pigsty.gpg /usr/share/keyrings/pigsty.gpg
COPY ./docker/database/pgdg.gpg /usr/share/keyrings/pgdg.gpg
COPY ./docker/debian.sources /etc/apt/sources.list.d/debian.sources
COPY ./docker/database/pigsty.sources /etc/apt/sources.list.d/pigsty.sources

RUN --mount=type=cache,target=/var/cache/apt/ \
    apt-get -o Acquire::https::Verify-Peer=false -o Acquire::https::Verify-Host=false update && \
    apt-get -o Acquire::https::Verify-Peer=false -o Acquire::https::Verify-Host=false -y install ca-certificates && \
    apt-get upgrade -y && \
    apt-get install -y  postgresql-18-vchord postgresql-18-vchord-bm25 postgresql-18-age && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    echo "zh_CN.UTF-8 UTF-8" >> /etc/locale.gen && \
    locale-gen && \
    rm -rf /tmp/*

# Redirect Schema
COPY ./docker/database/vchord_bm25.control /usr/share/postgresql/18/extension/
COPY ./docker/database/vchord_bm25--0.2.2--0.3.0.sql /usr/share/postgresql/18/extension/
VOLUME /var/lib/postgresql/18/docker
CMD ["postgres","-c","shared_preload_libraries=vchord,vchord_bm25,vector,age","-c","listen_addresses=0.0.0.0,::","-c","search_path='\"user\",public,ag_catalog,bm25_catalog'"]
