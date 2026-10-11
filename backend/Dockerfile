FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /src
COPY backend/pom.xml .
RUN mvn -q dependency:go-offline
COPY backend/src ./src
RUN mvn -q package -DskipTests

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /src/target/glucotwin-backend-1.0.0.jar app.jar
COPY data/ /data/
ENV GLUCOTWIN_DATA_DIR=/data
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
