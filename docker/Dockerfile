FROM python:3.8

# ChromeDriver installation from https://gist.github.com/varyonic/dea40abcf3dd891d204ef235c6e8dd79
# We need wget to set up the PPA and xvfb to have a virtual screen and unzip to install the Chromedriver
RUN apt-get update
RUN apt-get install -y libgconf-2-4 wget xvfb unzip

# Install chrome
RUN apt-get update && \
    apt-get install -y gnupg wget curl unzip --no-install-recommends && \
    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - && \
    echo "deb http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list && \
    apt-get update -y && \
    apt-get install -y google-chrome-stable


# Install chromedriver
ENV CHROMEDRIVER_DIR /chromedriver
RUN export CHROMEDRIVER_VERSION=$(google-chrome-stable --product-version) && \
    echo "$CHROMEDRIVER_VERSION" && \
    wget -q --continue -P $CHROMEDRIVER_DIR "https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/$CHROMEDRIVER_VERSION/linux64/chromedriver-linux64.zip"
RUN unzip $CHROMEDRIVER_DIR/chromedriver* -d $CHROMEDRIVER_DIR

RUN mv $CHROMEDRIVER_DIR/chromedriver-linux64/chromedriver $CHROMEDRIVER_DIR
RUN chmod 755 $CHROMEDRIVER_DIR

# Put Chromedriver into the PATH
ENV PATH $CHROMEDRIVER_DIR:$PATH

RUN mkdir -p /app/loconotion/
WORKDIR /app/loconotion/
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# comment out for debugging
ENTRYPOINT [ "python", "loconotion", "--chromedriver", "/chromedriver/chromedriver"]
