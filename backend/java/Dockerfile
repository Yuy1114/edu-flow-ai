FROM maven:3.9-eclipse-temurin-21 AS build

WORKDIR /build

# Cache dependencies layer. The BuildKit cache mount keeps ~/.m2 across builds:
# without it every rebuild re-downloads the whole tree, which is slow and turns
# any transient network hiccup into a failed image build.
COPY pom.xml .
RUN --mount=type=cache,target=/root/.m2 mvn dependency:go-offline -B

# Build
COPY src ./src
RUN --mount=type=cache,target=/root/.m2 mvn package -DskipTests -B \
    && mkdir -p /build/out && cp /build/target/*.jar /build/out/app.jar

# Runtime
FROM eclipse-temurin:21-jre

WORKDIR /app

COPY --from=build /build/out/app.jar app.jar

EXPOSE 8080

ENTRYPOINT [ "java", "-jar", "app.jar" ]
