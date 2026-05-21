# Based on discourse/discourse_docker image/discourse_dev/Dockerfile.
# The benchmark keeps discourse/discourse pinned through the upstream submodule.

ARG from_tag=slim

FROM discourse/base:$from_tag AS repo-fetcher
WORKDIR /repo
RUN chown discourse .
USER discourse
COPY --chown=discourse:discourse upstream/ ./

FROM discourse/base:$from_tag

RUN --mount=type=tmpfs,target=/var/log \
  apt-get -y update && DEBIAN_FRONTEND=noninteractive apt-get -y install \
  postgresql-${PG_MAJOR} postgresql-contrib-${PG_MAJOR} postgresql-${PG_MAJOR}-pgvector
RUN /tmp/install-redis

RUN rm -rf /var/www/*

ADD docker-upstream/image/discourse_dev/sudoers.discourse /etc/sudoers.d/discourse

RUN sudo -u discourse bundle config set --global path /home/discourse/.bundle/gems
RUN echo 'PATH="$(ruby -r rubygems -e "puts Gem.user_dir")/bin:$PATH"' >> /home/discourse/.profile

ADD docker-upstream/templates/redis.template.yml /pups/redis.yml
RUN /pups/bin/pups /pups/redis.yml

RUN locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8

ADD docker-upstream/templates/postgres.template.yml /pups/postgres.yml
RUN LANG=en_US.UTF-8 /pups/bin/pups /pups/postgres.yml

ADD docker-upstream/image/discourse_dev/postgres_dev.template.yml /pups/postgres_dev.yml
RUN /pups/bin/pups /pups/postgres_dev.yml

RUN mv /shared/postgres_data /shared/postgres_data_orig

ADD docker-upstream/image/discourse_dev/ensure-database /etc/runit/1.d/ensure-database

RUN wget -qO /tmp/mailhog https://github.com/mailhog/MailHog/releases/download/v1.0.1/MailHog_linux_amd64\
    && echo "e2ed634ded49929f089b20045581955ed217672078fd86082dd7a6c67c5d09c7 /tmp/mailhog" | sha256sum -c -\
    && mv /tmp/mailhog /usr/local/bin/mailhog\
    && chmod +x /usr/local/bin/mailhog\
    && rm -rf /tmp/*

USER discourse

RUN --mount=type=bind,src=/repo,from=repo-fetcher,target=/tmp/discourse-clone,readwrite \
    cd /tmp/discourse-clone \
    && bundle config set deployment true \
    && bundle install \
    && rm -rf /home/discourse/.bundle/gems/ruby/*/cache/*

RUN --mount=type=bind,src=/repo,from=repo-fetcher,target=/tmp/discourse-clone,readwrite \
    cd /tmp/discourse-clone \
    && (if [ -f yarn.lock ]; then yarn install; else CI=1 pnpm install; fi)

USER root
