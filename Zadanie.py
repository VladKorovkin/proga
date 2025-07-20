import sys
from flask import Flask, request, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, time
import math

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///meds.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JSON_AS_ASCII'] = False 
db = SQLAlchemy(app)

# Конфигурация сервиса
NEXT_TAKINGS_PERIOD = 60  # Период для приемов в минутах 
DAY_START = time(8, 0)    # Начало дня 
DAY_END = time(22, 0)     # Конец дня 

class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False)
    medication_name = db.Column(db.String(100), nullable=False)
    frequency = db.Column(db.Integer, nullable=False)  # в минутах
    start_date = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    duration = db.Column(db.Integer)  # в днях 

    def is_active(self, date):
        if self.duration is None:  # Бессрочное
            return date >= self.start_date
        end_date = self.start_date + timedelta(days=self.duration)
        return self.start_date <= date <= end_date

    def generate_times(self, date):
        if not self.is_active(date):
            return []
        
        current = datetime.combine(date, DAY_START)
        end_datetime = datetime.combine(date, DAY_END)
        times = set()

        while current <= end_datetime:
            # Округление времени до 15 минут вверх
            minutes = current.minute
            remainder = minutes % 15
            rounded_minutes = minutes if remainder == 0 else minutes + (15 - remainder)
            
            if rounded_minutes >= 60:
                current = current.replace(hour=current.hour+1, minute=0)
                if current.hour >= 24:  # Переход на следующий день
                    break
                rounded_minutes = 0
            
            rounded_time = current.replace(minute=rounded_minutes, second=0, microsecond=0)
            

            if rounded_time.time() <= DAY_END:
                times.add(rounded_time.time().strftime('%H:%M'))
            
            current += timedelta(minutes=self.frequency)
        
        return sorted(times)

@app.route('/schedule', methods=['POST'])
def create_schedule():
    data = request.json
    required_fields = ['user_id', 'medication_name', 'frequency', 'duration']
    
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        schedule = Schedule(
            user_id=data['user_id'],
            medication_name=data['medication_name'],
            frequency=int(data['frequency']),
            duration=int(data['duration']) if data['duration'] != -1 else None
        )
        db.session.add(schedule)
        db.session.commit()
        return jsonify({'schedule_id': schedule.id}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/schedules', methods=['GET'])
def get_schedules():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id parameter is required'}), 400
    
    schedules = Schedule.query.filter_by(user_id=user_id).all()
    return jsonify({'schedule_ids': [s.id for s in schedules]})

@app.route('/schedule', methods=['GET'])
def get_schedule():
    user_id = request.args.get('user_id')
    schedule_id = request.args.get('schedule_id')
    
    if not user_id or not schedule_id:
        return jsonify({'error': 'Both user_id and schedule_id are required'}), 400
    
    schedule = Schedule.query.filter_by(id=schedule_id, user_id=user_id).first()
    if not schedule:
        return jsonify({'error': 'Schedule not found'}), 404
    
    times = schedule.generate_times(datetime.utcnow().date())
    return jsonify({
        'schedule_id': schedule.id,
        'user_id': schedule.user_id,
        'medication_name': schedule.medication_name,
        'times': times
    })

@app.route('/next_takings', methods=['GET'])
def get_next_takings():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id parameter is required'}), 400
    
    now = datetime.utcnow()
    end_time = now + timedelta(minutes=NEXT_TAKINGS_PERIOD)
    
    schedules = Schedule.query.filter_by(user_id=user_id).all()
    takings = []
    
    for schedule in schedules:
        if schedule.is_active(now.date()):
            times = schedule.generate_times(now.date())
            for t in times:
                time_obj = datetime.strptime(t, '%H:%M').time()
                taking_time = datetime.combine(now.date(), time_obj)
                
                if now.time() <= time_obj <= end_time.time():
                    takings.append({
                        'medication_name': schedule.medication_name,
                        'time': t,
                        'schedule_id': schedule.id
                    })
    
    takings.sort(key=lambda x: x['time'])
    return jsonify({'takings': takings})

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  
    app.run(debug=True)
