import math
import os
import json
import glob

class MathUtils:
    @staticmethod
    def definitely_bigger(a, b, epsilon=1.0):
        return a - b > epsilon

    @staticmethod
    def logistic(x, midpoint_offset, multiplier, max_value=1.0):
        return max_value / (1.0 + math.exp(multiplier * (midpoint_offset - x)))

    @staticmethod
    def clamp(value, min_val, max_val):
        return max(min_val, min(value, max_val))

    @staticmethod
    def saturate(value):
        return MathUtils.clamp(value, 0.0, 1.0)

class HitObject:
    def __init__(self, start_time, end_time, column):
        self.start_time = float(start_time)
        self.end_time = float(end_time)
        self.column = column

class DifficultyHitObject:
    def __init__(self, base_object, previous, index, total_columns, speed=1.0):
        self.base_object = base_object
        self.previous = previous
        self.index = index
        self.start_time = base_object.start_time
        self.end_time = base_object.end_time
        self.column = base_object.column
        self.speed = speed

        self.previous_hit_objects = [None] * total_columns

        if previous is not None:
            self.delta_time = (self.start_time - previous.start_time) / speed
        else:
            self.delta_time = 0

        self.column_strain_time = 0

class IndividualStrainEvaluator:
    @staticmethod
    def evaluate_difficulty_of(current):
        start_time = current.start_time
        end_time = current.end_time
        hold_factor = 1.0

        for mania_previous in current.previous_hit_objects:
            if mania_previous is None:
                continue

            if MathUtils.definitely_bigger(mania_previous.end_time, end_time, 1) and \
               MathUtils.definitely_bigger(start_time, mania_previous.start_time, 1):
                hold_factor = 1.25
                break

        return 2.0 * hold_factor

class OverallStrainEvaluator:
    release_threshold = 30

    @classmethod
    def get_release_threshold(cls, speed=1.0):
        return cls.release_threshold / speed

    @staticmethod
    def evaluate_difficulty_of(current):
        start_time = current.start_time
        end_time = current.end_time
        is_overlapping = False
        
        closest_end_time = abs(end_time - start_time)
        hold_factor = 1.0
        hold_addition = 0

        for mania_previous in current.previous_hit_objects:
            if mania_previous is None:
                continue

            is_overlapping = is_overlapping or (
                MathUtils.definitely_bigger(mania_previous.end_time, start_time, 1) and
                MathUtils.definitely_bigger(end_time, mania_previous.end_time, 1) and
                MathUtils.definitely_bigger(start_time, mania_previous.start_time, 1)
            )

            if MathUtils.definitely_bigger(mania_previous.end_time, end_time, 1) and \
               MathUtils.definitely_bigger(start_time, mania_previous.start_time, 1):
                hold_factor = 1.25

            closest_end_time = min(closest_end_time, abs(end_time - mania_previous.end_time))

        if is_overlapping:
            hold_addition = MathUtils.logistic(closest_end_time, OverallStrainEvaluator.get_release_threshold(current.speed), 0.27, 1.0)

        return (1 + hold_addition) * hold_factor

class Strain:
    individual_decay_base = 0.125
    overall_decay_base = 0.30

    def __init__(self, columns, speed=1.0):
        self.current_section_peak = 0
        self.current_section_end = 0
        self.section_length = 400 / speed
        self.decay_weight = 0.9
        
        self.strain_peaks = []
        self.object_strains = []
        
        self.highest_individual_strain = 1.0
        self.overall_strain = 1.0
        self.total_columns = columns
        self.individual_strains = [0.0] * columns
        self.current_strain = 0.0

    def process(self, current):
        if current.index == 0:
            self.current_section_end = math.ceil(current.start_time / self.section_length) * self.section_length
            self.current_strain = self.calculate_initial_strain(self.current_section_end, current)

        while current.start_time > self.current_section_end:
            self.save_current_peak()
            self.start_new_section_from(self.current_section_end, current)
            self.current_section_end += self.section_length

        self.current_strain = self.strain_value_at(current)
        self.current_section_peak = max(self.current_strain, self.current_section_peak)
        self.object_strains.append(self.current_strain)

    def strain_value_at(self, current):
        # strainDecayBase in StrainDecaySkill is 1.0, so pow(1.0, x) is always 1.0
        # which means self.current_strain *= 1.0
        self.current_strain += self.strain_value_of(current)
        return self.current_strain

    def apply_decay(self, value, delta_time, decay_base):
        return value * math.pow(decay_base, delta_time / 1000.0)

    def calculate_initial_strain(self, offset, current):
        if current.index == 0 or current.previous is None:
            return 0
        return self.apply_decay(self.highest_individual_strain, offset - current.previous.start_time, self.individual_decay_base) + \
               self.apply_decay(self.overall_strain, offset - current.previous.start_time, self.overall_decay_base)

    def strain_value_of(self, current):
        self.individual_strains[current.column] = self.apply_decay(
            self.individual_strains[current.column],
            current.column_strain_time,
            self.individual_decay_base
        )
        self.individual_strains[current.column] += IndividualStrainEvaluator.evaluate_difficulty_of(current)

        if current.delta_time <= 1:
            self.highest_individual_strain = max(self.highest_individual_strain, self.individual_strains[current.column])
        else:
            self.highest_individual_strain = self.individual_strains[current.column]

        self.overall_strain = self.apply_decay(self.overall_strain, current.delta_time, self.overall_decay_base)
        self.overall_strain += OverallStrainEvaluator.evaluate_difficulty_of(current)

        return self.highest_individual_strain + self.overall_strain - self.current_strain

    def save_current_peak(self):
        self.strain_peaks.append(self.current_section_peak)

    def start_new_section_from(self, time, current):
        self.current_section_peak = self.calculate_initial_strain(time, current)

    def difficulty_value(self):
        difficulty = 0.0
        weight = 1.0

        peaks = [p for p in self.strain_peaks if p > 0]
        if self.current_section_peak > 0:
            peaks.append(self.current_section_peak)

        peaks.sort(reverse=True)

        for p in peaks:
            difficulty += p * weight
            weight *= self.decay_weight

        return difficulty


class DifficultyCalculator:
    difficulty_multiplier = 0.018

    def __init__(self, hit_objects, total_columns, speed=1.0):
        self.hit_objects = sorted(hit_objects, key=lambda x: x.start_time)
        self.total_columns = total_columns
        self.speed = speed

    def create_difficulty_hit_objects(self):
        objects = []
        if len(self.hit_objects) <= 1:
            return objects

        for i in range(len(self.hit_objects) - 1):
            prev = objects[i - 1] if i > 0 else None
            objects.append(DifficultyHitObject(
                self.hit_objects[i + 1], prev, i + 1, self.total_columns, self.speed))

        for i in range(len(objects)):
            if i > 0:
                for k in range(self.total_columns):
                    objects[i].previous_hit_objects[k] = objects[i - 1].previous_hit_objects[k]
                prev_column = objects[i - 1].column
                objects[i].previous_hit_objects[prev_column] = objects[i - 1]

        for i in range(len(objects)):
            col = objects[i].column
            if 0 <= col < self.total_columns:
                prev_in_column = None
                for j in range(i - 1, -1, -1):
                    if objects[j].column == col:
                        prev_in_column = objects[j]
                        break
                
                if prev_in_column is not None:
                    objects[i].column_strain_time = (objects[i].start_time - prev_in_column.start_time) / self.speed
                else:
                    objects[i].column_strain_time = objects[i].start_time / self.speed

        return objects

    def calculate_difficulty(self):
        if not self.hit_objects:
            return 0.0

        difficulty_objects = self.create_difficulty_hit_objects()

        if not difficulty_objects:
            return 0.0

        skill = Strain(self.total_columns, self.speed)

        for obj in difficulty_objects:
            skill.process(obj)

        star_rating = skill.difficulty_value() * self.difficulty_multiplier
        return star_rating

def calculate_stars_for_json(json_path, total_columns=4, speed=1.0):
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        notes = data.get('notes', [])
        hit_objects = []
        for note in notes:
            start_time = note.get('time', 0)
            end_time = note.get('end_time', start_time)
            column = note.get('lane', 0)
            hit_objects.append(HitObject(start_time, end_time, column))

        calc = DifficultyCalculator(hit_objects, total_columns, speed)
        stars = calc.calculate_difficulty()
        return stars
    except Exception as e:
        print(f"Error processing {json_path}: {e}")
        return 0.0

if __name__ == "__main__":
    songs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "songs")
    json_files = glob.glob(os.path.join(songs_dir, "**", "*.json"), recursive=True)
    json_files.extend(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "*.json")))
    
    print(f"{'Filename':<50} | {'Stars':<10}")
    print("-" * 65)
    for jf in json_files:
        if os.path.basename(jf) in ['config.json', 'history.json', 'package.json']:
            continue
        stars = calculate_stars_for_json(jf)
        name = os.path.basename(jf)
        if len(name) > 48:
            name = name[:45] + "..."
        print(f"{name:<50} | {stars:.4f}")
