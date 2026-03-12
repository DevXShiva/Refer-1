# Python 3.11 का उपयोग करें क्योंकि यह सबसे स्टेबल है
FROM python:3.11-slim

# सिस्टम को अपडेट करें और कंपाइलेशन के लिए जरूरी टूल्स डालें
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# वर्किंग डायरेक्टरी सेट करें
WORKDIR /app

# पहले रिक्वायरमेंट्स कॉपी करें ताकि लेयर कैशिंग का लाभ मिले
COPY requirements.txt .

# पाइपलाइन को अपग्रेड करें और लाइब्रेरीज़ इंस्टॉल करें
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# बाकी का पूरा कोड कॉपी करें
COPY . .

# Flask के लिए पोर्ट 8080 खोलें
EXPOSE 8080

# बॉट चलाने की कमांड
CMD ["python", "main.py"]
