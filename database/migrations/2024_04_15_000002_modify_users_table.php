<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('users', function (Blueprint $table) {
            $table->foreignId('company_id')->nullable()->after('id')->comment('기업 아이디');
            $table->enum('type', ['admin', 'tester', 'owner'])->after('company_id')->comment('타입');
            $table->string('mobile')->nullable()->after('type')->comment('휴대전화');
            $table->string('biz_no')->nullable()->after('mobile')->comment('사업자등록번호');
            $table->string('tid')->unique()->after('biz_no')->comment('로그인 아이디');

            // email 필드는 nullable 유지
            $table->string('email')->nullable()->comment('이메일')->change();

            // 외래키 제약조건 추가
            $table->foreign('company_id')->references('id')->on('companies')->onDelete('set null');
        });
    }

    public function down(): void
    {
        Schema::table('users', function (Blueprint $table) {
            $table->dropForeign(['company_id']);
            $table->dropColumn(['company_id', 'type', 'mobile', 'biz_no', 'tid']);
            // email 필드는 nullable 유지
            $table->string('email')->nullable()->change();
        });
    }
};
