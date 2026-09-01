<?php

namespace Database\Factories;

use Illuminate\Database\Eloquent\Factories\Factory;

class ScanCodeFactory extends Factory
{
    public function definition(): array
    {
        return [
            'type' => fake()->randomElement(['ev', 'ice']),
            'scan_id' => null,
            'code_id' => null,
        ];
    }
}
