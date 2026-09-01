<?php

namespace Database\Seeders;

use App\Models\Company;
use App\Models\User;
use App\Models\Code;
use App\Models\Scan;
use App\Models\ScanCode;
// use Illuminate\Database\Console\Seeds\WithoutModelEvents;
use Illuminate\Database\Seeder;

class DatabaseSeeder extends Seeder
{
    /**
     * Seed the application's database.
     */
    public function run(): void
    {
        // 기업 생성
        $companies = Company::factory(5)->create();

        // 테스트 계정 생성
        $this->call([
            UserSeeder::class,
        ]);

        // 각 기업별로 사용자 생성
        $companies->each(function ($company) {
            // 관리자 생성
            User::factory()->create([
                'company_id' => $company->id,
                'type' => 'admin',
            ]);

            // 테스터 생성
            User::factory(2)->create([
                'company_id' => $company->id,
                'type' => 'tester',
            ]);

            // 소유자 생성
            User::factory(3)->create([
                'company_id' => $company->id,
                'type' => 'owner',
            ]);
        });

        // 진단 코드 생성
        $codes = Code::factory(50)->create();

        // 스캔 데이터 생성
        $users = User::all();
        $users->each(function ($user) use ($codes) {
            // 테스터인 경우에만 스캔 생성
            if ($user->type === 'tester') {
                // 소유자가 있는 스캔 생성
                $scans = Scan::factory(5)->create([
                    'tester_id' => $user->id,
                    'company_id' => $user->company_id,
                ]);

                // 소유자가 없는 스캔 생성
                $scansWithoutOwner = Scan::factory(3)
                    ->withoutOwner()
                    ->create([
                        'tester_id' => $user->id,
                'company_id' => $user->company_id,
            ]);

                $allScans = $scans->concat($scansWithoutOwner);

            // 각 스캔에 대해 진단 코드 연결
                $allScans->each(function ($scan) use ($codes) {
                $scanCodes = $codes->random(rand(1, 5));
                foreach ($scanCodes as $code) {
                    ScanCode::factory()->create([
                        'scan_id' => $scan->id,
                        'code_id' => $code->id,
                        'type' => $scan->type,
                    ]);
                }
            });
            }
        });
    }
}
