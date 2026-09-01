<?php

namespace Database\Factories;

use Illuminate\Database\Eloquent\Factories\Factory;
use App\Models\User;
use App\Models\Company;

class ScanFactory extends Factory
{
    public function definition(): array
    {
        return [
            'type' => fake()->randomElement(['ev', 'ice']),
            'device_type' => fake()->randomElement(['OBD2', 'ELM327', 'VCI']),
            'device_uid' => fake()->unique()->uuid(),
            'owner_id' => User::factory(),
            'tester_id' => User::factory(),
            'company_id' => Company::factory(),
            'scan_vin' => fake()->regexify('[A-HJ-NPR-Z0-9]{17}'),
            'car_no' => fake()->numberBetween(10, 99) . mb_substr("가나다라마바사아자차카타파하", rand(0, 13), 1) . fake()->numberBetween(1000, 9999),
            'car_vin' => fake()->regexify('[A-HJ-NPR-Z0-9]{17}'),
            'car_model' => fake()->randomElement(['그랜저', '소나타', '아반떼', '코나', '아이오닉']),
            'car_cc' => fake()->numberBetween(1000, 5000),
            'car_year' => fake()->numberBetween(2010, 2024),
            'car_fuel' => fake()->randomElement(['가솔린', '디젤', 'LPG', '전기']),
            'car_battery_capacity' => fake()->optional()->randomFloat(2, 20, 100),
            'car_discharge_energy' => fake()->optional()->randomFloat(2, 1000, 10000),
            'car_charge_energy' => fake()->optional()->randomFloat(2, 1000, 10000),
            'raw' => [
                'scan_time' => now()->toIso8601String(),
                'device_info' => [
                    'manufacturer' => fake()->company(),
                    'model' => fake()->word(),
                    'firmware' => fake()->numerify('v#.#.#'),
                ],
                'diagnostic_data' => [
                    'dtcs' => [],
                    'freeze_frame' => [],
                    'live_data' => [],
                ],
            ],
        ];
    }

    /**
     * 소유자가 없는 스캔을 생성합니다.
     */
    public function withoutOwner(): static
    {
        return $this->state(fn (array $attributes) => [
            'owner_id' => null,
        ]);
    }
}
