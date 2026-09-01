<?php

namespace Database\Seeders;

use App\Models\Company;
use App\Models\User;
use Illuminate\Database\Seeder;
use Illuminate\Support\Facades\Hash;

class UserSeeder extends Seeder
{
    public function run(): void
    {
        // 회사가 없는 경우 생성
        $company = Company::factory()->create([
            'code' => 'COMPANY',
            'name' => '테스트 회사',
        ]);

        // 테스트 계정 생성
        $testUsers = [
            [
                'tid' => 'owner',
                'name' => '소유자',
                'email' => 'owner@example.com',
                'password' => 'password123',
                'type' => 'owner',
                'mobile' => '01000000001',
                'company_id' => $company->id,
            ],
            [
                'tid' => 'admin',
                'name' => '관리자',
                'email' => 'admin@example.com',
                'password' => 'password123',
                'type' => 'admin',
                'mobile' => '01000000002',
                'company_id' => $company->id,
            ],
            [
                'tid' => 'tester',
                'name' => '테스터',
                'email' => 'tester@example.com',
                'password' => 'password123',
                'type' => 'tester',
                'mobile' => '01000000003',
                'company_id' => $company->id,
            ],
        ];

        foreach ($testUsers as $user) {
            User::create([
                'tid' => $user['tid'],
                'name' => $user['name'],
                'email' => $user['email'],
                'password' => $user['password'],
                'type' => $user['type'],
                'mobile' => $user['mobile'],
                'company_id' => $user['company_id'],
            ]);
        }
    }
}
