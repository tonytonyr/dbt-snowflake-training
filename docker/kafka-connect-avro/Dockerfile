FROM confluentinc/cp-kafka-connect-base:7.6.1

# Debezium 3.x requires Java 17; this base image (Confluent Platform 7.6) ships
# Java 11. Debezium 2.5.x is the last line compatible with Java 11 — confirmed
# empirically (3.2.6-2 fails at Connect startup with UnsupportedClassVersionError).
RUN confluent-hub install --no-prompt debezium/debezium-connector-postgresql:2.5.4-2 && \
    confluent-hub install --no-prompt confluentinc/kafka-connect-avro-converter:8.3.0
