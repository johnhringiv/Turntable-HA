# Use the official Python image from the Docker Hub
FROM python:3.13-alpine AS builder

# Set the working directory in the container
WORKDIR /app

RUN apk update && \
    apk add --no-cache gcc musl-dev linux-headers

RUN pip install --upgrade pip uv
RUN python -m venv /opt/venv

# Enable venv
ENV PATH="/opt/venv/bin:$PATH"

# Needed for netifaces (dep for denonavr) to work
ENV CFLAGS="-Wno-int-conversion"

COPY uv.lock ./
RUN uv pip sync uv.lock

FROM python:3.13-alpine

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Enable venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy the application code into the container
COPY turntable_ha/ /app/turntable_ha/

# Create a directory for the database
RUN mkdir -p /data


# Set environment variables, these aren't secrets so it's fine to set them here
ENV RECEIVER_IP="192.168.55.22"
ENV TT_URL="http://192.168.55.203"
ENV PRE_AMP_URL="http://192.168.55.165"
ENV TT_INPUT="CD"
ENV SOUND_MODE="STEREO"
ENV VOLUME=-30
ENV SHUTDOWN_DELAY=300
ENV DB_FOLDER="/data"

# Run the application
CMD ["python", "turntable_ha/main.py"]