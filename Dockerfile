# Use the official Python image from the Docker Hub
FROM python:3.13 AS builder

# Set the working directory in the container
WORKDIR /app

RUN python -m venv /opt/venv
# Enable venv
ENV PATH="/opt/venv/bin:$PATH"

# Install the dependencies
RUN --mount=type=bind,source=requirements.txt,target=requirements.txt \
    pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

FROM python:3.13-slim

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Enable venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy the application code into the container
COPY src/*.py .

# Create a directory for the database
RUN mkdir -p /data


# Set environment variables, these aren't secrets so it's fine to set them here
ENV RECEIVER_IP="192.168.55.22"
ENV TT_URL="http://192.168.55.203"
ENV PRE_AMP_URL="http://192.168.55.205"
ENV TT_INPUT="CD"
ENV SOUND_MODE="PURE DIRECT"
ENV VOLUME=-30
ENV SHUTDOWN_DELAY=300
ENV DB_FOLDER="/data"

# Run the application
CMD ["python", "main.py"]