# Use the official Python image from the Docker Hub
FROM python:3.13-alpine

# Set the working directory in the container
WORKDIR /app

# Copy the requirements files into the container
COPY requirements.txt ./

# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY src/*.py .

# Create a directory for the database
RUN mkdir -p /data


# Create a directory for the database
RUN mkdir -p /data


# Set environment variables, these aren't secrets so it's fine to set them here
ENV RECEIVER_IP="192.168.55.22"
ENV TT_URL="http://192.168.55.203"
ENV PRE_AMP_URL="http://192.168.55.205"
ENV TT_INPUT="CD"
ENV SOUND_MODE="PURE%20DIRECT"
ENV VOLUME=30
ENV SHUTDOWN_DELAY=300
ENV DB_FOLDER="/data"

# Run the application
CMD ["python", "main.py"]