<?php

namespace Database\Factories;

use App\Models\CarMismatchReport;
use App\Models\User;
use Illuminate\Database\Eloquent\Factories\Factory;

/**
 * @extends \Illuminate\Database\Eloquent\Factories\Factory<\App\Models\CarMismatchReport>
 */
class CarMismatchReportFactory extends Factory
{
    protected $model = CarMismatchReport::class;

    /**
     * Define the model's default state.
     *
     * @return array<string, mixed>
     */
    public function definition(): array
    {
        return [
            'user_id' => User::factory(),
            'car_no' => $this->faker->regexify('[0-9]{2}[가-힣][0-9]{4}'),
            'api_vin' => $this->faker->regexify('[A-Z0-9]{17}'),
            'scan_vin' => $this->faker->regexify('[A-Z0-9]{17}'),
        ];
    }
}
